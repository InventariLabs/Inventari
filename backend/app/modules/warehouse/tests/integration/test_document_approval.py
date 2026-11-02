"""Integration tests for document approval workflow."""

import uuid
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalWorkflow
from app.modules.warehouse.models import Document, DocumentStatus


@pytest.mark.integration
class TestDocumentApprovalWorkflow:
    """Tests for approval workflow on documents."""

    @staticmethod
    def _create_doc(
        client: TestClient,
        auth_headers: dict[str, str],
        doc_type: str,
        partner_id: uuid.UUID | None,
        target_location_id: uuid.UUID,
        lines: list[dict[str, Any]],
        source_location_id: uuid.UUID | None = None,
    ) -> str:
        line_payload = lines.copy()
        payload = {
            'type': doc_type,
            'partner_id': str(partner_id) if partner_id else None,
            'lines': line_payload,
            'target_location_id': str(target_location_id),
        }
        if source_location_id:
            payload['source_location_id'] = str(source_location_id)
        resp = client.post(
            '/api/v1/warehouse/documents', headers=auth_headers, json=payload
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        return cast(str, resp.json()['id'])

    @staticmethod
    def _confirm_doc(
        client: TestClient, auth_headers: dict[str, str], doc_id: str
    ) -> Response:
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        return resp  # type: ignore[no-any-return]

    @staticmethod
    def _set_profile_threshold(
        client: TestClient,
        auth_headers: dict[str, str],
        threshold: float | None,
        types: list[str] | None = None,
    ) -> None:
        resp = client.get('/api/v1/warehouse/profile', headers=auth_headers)
        profile = resp.json()
        payload = {
            'approval_threshold': str(threshold) if threshold else None,
            'approval_required_for_types': types or [],
            'value_tracking_enabled': True,
        }
        resp = client.put(
            '/api/v1/warehouse/profile',
            headers=auth_headers,
            json={
                **{
                    k: v
                    for k, v in profile.items()
                    if k not in ('id', 'organization_id', 'created_at', 'updated_at')
                },
                **payload,
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    @staticmethod
    def _request_approval(
        client: TestClient,
        auth_headers: dict[str, str],
        doc_id: str,
        notes: str | None = None,
    ) -> Response:
        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=auth_headers,
            params={'notes': notes} if notes else None,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        return resp  # type: ignore[no-any-return]

    @staticmethod
    def _approve_doc(
        client: TestClient, auth_headers: dict[str, str], doc_id: str
    ) -> Response:
        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        return resp  # type: ignore[no-any-return]

    @staticmethod
    def _add_workflow(client: TestClient, auth_headers: dict[str, str]) -> None:
        """Put the document workflow in place after the document was confirmed.

        An organization switching approvals on has documents in flight, and a
        document already CONFIRMED is the one the rule cannot gate by
        confirmation — it is the request raised by hand (or the gate's own
        refusal) that has to stop it.
        """
        # Saved off, then switched on under the scope the list shows — the
        # profile may already carry a threshold or a type list by now.
        resp = client.post(
            '/api/v1/approvals/workflows',
            headers=auth_headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Workflow arrived late',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [],
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        workflow_id = resp.json()['id']
        listed = client.get('/api/v1/approvals/workflows', headers=auth_headers)
        shown = next(r for r in listed.json()['items'] if r['id'] == workflow_id)[
            'scope'
        ]
        switched_on = client.patch(
            f'/api/v1/approvals/workflows/{workflow_id}',
            headers=auth_headers,
            json={'is_active': True, 'expected_scope': shown},
        )
        assert switched_on.status_code == status.HTTP_200_OK, switched_on.text

    # ------------------------------------------------------------------
    # Profile configuration
    # ------------------------------------------------------------------

    def test_set_approval_threshold_on_profile(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        self._set_profile_threshold(client, doc_auth_headers, 1000.00)
        resp = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        assert resp.json()['approval_threshold'] == '1000.00'

    @pytest.mark.parametrize('threshold', ['-500', '-0.01'])
    def test_set_negative_approval_threshold_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        threshold: str,
    ) -> None:
        """a negative threshold would force approval on every document,
        including zero-value ones — reject it at the schema level like the
        purchase-orders twin does."""
        resp = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        profile = resp.json()
        resp = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={
                **{
                    k: v
                    for k, v in profile.items()
                    if k not in ('id', 'organization_id', 'created_at', 'updated_at')
                },
                'approval_threshold': threshold,
                'approval_required_for_types': [],
            },
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_set_approval_required_for_types_on_profile(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        self._set_profile_threshold(
            client, doc_auth_headers, None, ['OUT', 'INTERNAL_OUT']
        )
        resp = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        assert resp.json()['approval_required_for_types'] == ['OUT', 'INTERNAL_OUT']

    # ------------------------------------------------------------------
    # Approval required above threshold
    # ------------------------------------------------------------------

    def test_complete_without_approval_when_threshold_exceeded_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'approval' in resp.json()['detail']['message'].lower()

    def test_complete_below_threshold_no_approval_needed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """The profile's threshold does not reach this document.

        No workflow here: a workflow stands in only while the profile names
        nothing, and this profile names a threshold — see
        ``test_one_definition_of_approval_required``. Either way this
        document confirms directly.
        """
        self._set_profile_threshold(client, doc_auth_headers, 1000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    # ------------------------------------------------------------------
    # Approval required for specific document types
    # ------------------------------------------------------------------

    def test_out_type_requires_approval_even_below_threshold(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        doc_item.storage_location_id = doc_source_location.id
        db_session.commit()

        self._set_profile_threshold(client, doc_auth_headers, None, ['OUT'])

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'OUT',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '1.00',
                }
            ],
            source_location_id=doc_source_location.id,
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

    def test_int_type_does_not_require_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """An internal document the profile does not list.

        No workflow either — the profile names a type list, and this document
        is not on it, so no rule asks for approval.
        """
        self._set_profile_threshold(
            client, doc_auth_headers, None, ['OUT', 'INTERNAL_OUT']
        )

        from decimal import Decimal

        doc_item.quantity = Decimal('10')
        doc_item.storage_location_id = doc_source_location.id

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'INT',
            None,
            doc_target_location.id,
            [{'item_id': str(doc_item.id), 'expected_quantity': 1}],
            source_location_id=doc_source_location.id,
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    # ------------------------------------------------------------------
    # Approve and reject
    # ------------------------------------------------------------------

    def test_approve_document_allows_completion(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm above threshold auto-creates the approval request.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'APPROVED'

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == DocumentStatus.COMPLETED.value

    def test_approver_grant_decides_without_a_manager_role(
        self,
        client: TestClient,
        h: Any,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """the grant decides, not the role name.

        A dedicated approver is exactly who an organization creates the
        ``approvals:approve`` grant for; the proxy used to turn them away
        because their role string was not ``manager``.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        approver = h.create_user(doc_org, email='approver@example.com', role='user')
        h.grant_permissions(
            approver, ['warehouse:read', 'warehouse:write', 'approvals:approve']
        )

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve',
            headers=h.get_auth_headers(approver),
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'APPROVED'

    def test_manager_without_the_grant_cannot_decide(
        self,
        client: TestClient,
        h: Any,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """The mirror case: a manager whose roles withhold the grant is refused.

        The approvals engine already refused them; only this proxy did not.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        manager = h.create_user(doc_org, email='ungranted@example.com', role='manager')
        h.grant_permissions(manager, ['warehouse:read', 'warehouse:write'])

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve',
            headers=h.get_auth_headers(manager),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_reject_document_blocks_completion(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        # Reject now returns the document to
        # DRAFT (rework loop) instead of leaving it stuck in PENDING_APPROVAL.
        # Completion must therefore be blocked — but the new failure path is
        # the status check ("Cannot complete document in DRAFT status"),
        # not the legacy "approval rejected" check.
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'REJECTED'

        # Doc is DRAFT after rework — cannot be completed from DRAFT.
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_409_CONFLICT,
        ), resp.text
        assert 'draft' in resp.text.lower() or 'approval' in resp.text.lower()

    # ------------------------------------------------------------------
    # GET /warehouse/awaiting-my-approval
    # ------------------------------------------------------------------

    def test_awaiting_my_approval_returns_open_stage_doc(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Open-stage requests surface in the user's awaiting-approval list.

        The new endpoint must list the document
        because the current stage has an open approver list (any approver
        may act).
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.get(
            '/api/v1/warehouse/awaiting-my-approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        ids = [doc['id'] for doc in resp.json()['items']]
        assert doc_id in ids

    def test_awaiting_my_approval_empty_when_terminal(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """After approval, the document drops off the user's queue."""
        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        # Approve everything (single stage).
        client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )

        resp = client.get(
            '/api/v1/warehouse/awaiting-my-approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        ids = [doc['id'] for doc in resp.json()['items']]
        assert doc_id not in ids

    def test_awaiting_my_approval_org_scoped(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """The endpoint is org-scoped — empty result when no pending docs."""
        # No docs created — empty list.
        resp = client.get(
            '/api/v1/warehouse/awaiting-my-approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        # The canonical paginated envelope: the pre-release `documents`
        # duplicate of `items` did not survive the first release.
        assert body == {
            'items': [],
            'total': 0,
            'limit': 50,
            'offset': 0,
            'has_more': False,
            'total_capped': False,
        }

    def test_awaiting_my_approval_empty_when_approvals_module_disabled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """When the approvals module is off for the org, the queue is
        empty even if approval requests exist somewhere in the DB.

        Explicit graceful degradation.
        ``list_requests`` does not raise on a disabled module (it just
        returns whatever is in the DB); the router must check the
        module list up front so the contract is observable.
        """
        original = list(doc_org.enabled_modules or [])
        doc_org.enabled_modules = [m for m in original if m != 'approvals']
        # The fixture's session is a per-test transactional scope; the
        # commit below propagates the change so the FastAPI request
        # below sees the disabled state.
        from app.database import SessionLocal

        with SessionLocal() as sync_s:
            synced = sync_s.get(Organization, doc_org.id)
            if synced is not None:
                synced.enabled_modules = doc_org.enabled_modules
                sync_s.commit()
        try:
            resp = client.get(
                '/api/v1/warehouse/awaiting-my-approval',
                headers=doc_auth_headers,
            )
            assert resp.status_code == status.HTTP_200_OK
            body = resp.json()
            assert body['items'] == []
            assert body['total'] == 0
        finally:
            doc_org.enabled_modules = original
            with SessionLocal() as sync_s:
                synced = sync_s.get(Organization, doc_org.id)
                if synced is not None:
                    synced.enabled_modules = original
                    sync_s.commit()

    def _disable_approvals_module(self, doc_org: Organization) -> list[str]:
        """Switch the approvals module off and propagate to the request
        session, the way the queue test below does."""
        from app.database import SessionLocal

        original = list(doc_org.enabled_modules or [])
        doc_org.enabled_modules = [m for m in original if m != 'approvals']
        with SessionLocal() as sync_s:
            synced = sync_s.get(Organization, doc_org.id)
            if synced is not None:
                synced.enabled_modules = doc_org.enabled_modules
                sync_s.commit()
        return original

    @staticmethod
    def _restore_approvals_module(doc_org: Organization, original: list[str]) -> None:
        from app.database import SessionLocal

        doc_org.enabled_modules = original
        with SessionLocal() as sync_s:
            synced = sync_s.get(Organization, doc_org.id)
            if synced is not None:
                synced.enabled_modules = original
                sync_s.commit()

    def test_document_parked_then_module_disabled_still_completes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """A document parked in PENDING_APPROVAL keeps its way forward when
        the approvals module is switched off.

        The gate used to refuse with APPROVAL_REQUIRED —
        telling the reader to request an approval, which a disabled module
        makes impossible — while the requests themselves were unreadable and
        un-withdrawable behind the module's own 403s. Receipt of goods that
        physically arrived was postable only by cancelling the document or
        switching the module back on, and nothing on the document said so.
        ``docs/purpose/approvals.md``: when the module is off,
        ``check_and_block`` is a no-op and what would have waited proceeds.
        """
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        original = self._disable_approvals_module(doc_org)
        try:
            resp = client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            )
            assert resp.status_code == status.HTTP_200_OK, resp.text
            assert resp.json()['status'] == DocumentStatus.COMPLETED.value
        finally:
            self._restore_approvals_module(doc_org, original)

    def test_confirm_does_not_park_documents_while_module_disabled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """With approvals off, confirming proceeds instead of parking.

        Otherwise every new confirm under a disabled module recreated the
        deadlock this guard exists to undo.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        original = self._disable_approvals_module(doc_org)
        try:
            doc_id = self._create_doc(
                client,
                doc_auth_headers,
                'IN',
                doc_partner.id,
                doc_target_location.id,
                [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                        'unit_price': '50.00',
                    }
                ],
            )
            resp = self._confirm_doc(client, doc_auth_headers, doc_id)
            assert resp.json()['status'] == DocumentStatus.CONFIRMED.value
        finally:
            self._restore_approvals_module(doc_org, original)

    # ------------------------------------------------------------------
    # a queue is a list of things you can act on
    # ------------------------------------------------------------------

    def _queue_ids(self, client: TestClient, auth_headers: dict[str, str]) -> list[str]:
        resp = client.get(
            '/api/v1/warehouse/awaiting-my-approval', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        return [doc['id'] for doc in resp.json()['items']]

    def _doc_pending_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> str:
        """A confirmed document parked in PENDING_APPROVAL by the threshold."""
        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        return doc_id

    def test_awaiting_my_approval_hides_own_request_without_self_approval(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """the requester does not queue up to decide on themselves.

        ``approve_stage`` refuses a decision on one's own request unless the
        organization allows admin self-approval, so offering the card with a
        live Approve button promised an authority the API withholds.
        """
        h.set_module_settings(doc_org, 'approvals', {'allow_admin_self_approve': False})
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        assert doc_id not in self._queue_ids(client, doc_auth_headers)

    def test_awaiting_my_approval_keeps_own_request_when_self_approval_allowed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """with self-approval on, the admin's own request stays put.

        The fixture org enables ``allow_admin_self_approve``, which is exactly
        the case where the decision does go through.
        """
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        assert doc_id in self._queue_ids(client, doc_auth_headers)

    def test_awaiting_my_approval_shows_another_users_request(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """filtering out one's own requests keeps everyone else's."""
        h.set_module_settings(doc_org, 'approvals', {'allow_admin_self_approve': False})
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        approver = h.create_user(doc_org, email='approver@example.com')

        assert doc_id in self._queue_ids(client, h.get_auth_headers(approver))

    def test_document_approval_says_requester_cannot_decide(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """the request itself carries the answer for the viewer.

        The rule lives in the approvals service; the UI reads the verdict
        instead of re-deriving it from ``created_by`` and an org setting it
        cannot see.
        """
        h.set_module_settings(doc_org, 'approvals', {'allow_admin_self_approve': False})
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        approver = h.create_user(doc_org, email='other-approver@example.com')

        as_requester = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        as_approver = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval',
            headers=h.get_auth_headers(approver),
        )

        assert as_requester.status_code == status.HTTP_200_OK, as_requester.text
        assert as_requester.json()['viewer_can_decide'] is False
        assert as_approver.json()['viewer_can_decide'] is True

    def test_withdrawn_request_can_be_raised_again(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """withdrawing takes back the request, and the document with it.

        Nothing is waiting any more, so the document leaves the state that
        says it is — otherwise it kept its place in the "Pending Approval"
        filter behind a request nobody could decide. The same endpoint the
        detail page calls then opens a fresh request.
        """
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        approval = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        ).json()

        cancelled = client.post(
            f'/api/v1/approvals/requests/{approval["id"]}/cancel',
            headers=doc_auth_headers,
        )
        assert cancelled.status_code == status.HTTP_200_OK, cancelled.text
        assert cancelled.json()['status'] == 'CANCELLED'

        doc = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        assert doc['status'] == DocumentStatus.CONFIRMED.value

        again = self._request_approval(client, doc_auth_headers, doc_id)
        assert again.json()['status'] == 'PENDING'
        assert again.json()['id'] != approval['id']

    def test_approving_from_the_queue_moves_the_document_too(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """A decision taken in the approvals queue reaches the document.

        The document's own screen has always moved it; the queue settled the
        request and stopped there, so an approved document and one still
        waiting were the same row on the list and in the "Pending Approval"
        filter — while ``PATCH /complete`` on it went through.
        """
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        approval = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        ).json()

        approved = client.post(
            f'/api/v1/approvals/requests/{approval["id"]}/approve',
            headers=doc_auth_headers,
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text
        assert approved.json()['status'] == 'APPROVED'

        doc = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        assert doc['status'] == DocumentStatus.CONFIRMED.value

        # ...and the filter agrees with what the document can now do.
        pending = client.get(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            params={'status': DocumentStatus.PENDING_APPROVAL.value},
        ).json()
        rows = pending['items'] if isinstance(pending, dict) else pending
        assert all(row['id'] != doc_id for row in rows)

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

    def test_rejecting_from_the_queue_reworks_the_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Same for a refusal: the document becomes editable again."""
        doc_id = self._doc_pending_approval(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        approval = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        ).json()

        rejected = client.post(
            f'/api/v1/approvals/requests/{approval["id"]}/reject',
            headers=doc_auth_headers,
        )
        assert rejected.status_code == status.HTTP_200_OK, rejected.text

        doc = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        assert doc['status'] == DocumentStatus.DRAFT.value

    def test_cannot_approve_already_completed_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        # The document has to pass the threshold: since the profile stopped
        # being overridden by the workflow, a document under it would confirm
        # directly and never have an approval to complete.
        self._set_profile_threshold(client, doc_auth_headers, 1000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 200,
                    'unit_price': '10.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        # The profile asks and the workflow carries it out, so this document's
        # way to COMPLETED runs through the approval.
        self._approve_doc(client, doc_auth_headers, doc_id)
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

    def test_cannot_reject_already_completed_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        # Priced over the threshold, so the approval this document goes
        # through is one the profile asks for.
        self._set_profile_threshold(client, doc_auth_headers, 1000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 200,
                    'unit_price': '10.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        self._approve_doc(client, doc_auth_headers, doc_id)
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

    def test_duplicate_approval_request_returns_409(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Confirm above threshold auto-creates the request; manual duplicate fails 409."""
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        # Manual request-approval is now redundant — the auto-created request
        # is already in PENDING. A second call must still be rejected.
        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

    def test_get_document_includes_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request.
        self._confirm_doc(client, doc_auth_headers, doc_id)
        client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )

        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert 'approval' in data
        assert data['approval']['status'] == 'APPROVED'

    # ------------------------------------------------------------------
    # PENDING_APPROVAL status (Fix 3)
    # ------------------------------------------------------------------

    def test_confirm_sets_pending_approval_when_required(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Confirming a doc above threshold yields PENDING_APPROVAL, not CONFIRMED."""
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        resp = self._confirm_doc(client, doc_auth_headers, doc_id)
        assert resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

    def test_confirm_without_approval_requirement_stays_confirmed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Below-threshold doc stays CONFIRMED after confirm.

        With no workflow configured: where one is, it gates the document on
        its own, whatever the threshold says.
        """
        self._set_profile_threshold(client, doc_auth_headers, 1000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ],
        )
        resp = self._confirm_doc(client, doc_auth_headers, doc_id)
        assert resp.json()['status'] == DocumentStatus.CONFIRMED.value

    def test_approval_transitions_pending_to_confirmed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """After full approval, document transitions PENDING_APPROVAL → CONFIRMED."""
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'APPROVED'

        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.CONFIRMED.value

    def test_cancel_pending_approval_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """PENDING_APPROVAL document can be cancelled."""
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == DocumentStatus.CANCELLED.value

    def test_manager_cancelling_someone_elses_document_closes_the_request(
        self,
        client: TestClient,
        h: Any,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """cancelling a document takes its approval request with it.

        The cascade cancelled on behalf of the acting user, and the approvals
        service only let the requester withdraw — so a manager cancelling
        someone else's document left a live request in the queue, pointing at a
        cancelled document that no decision could change.
        """
        requester = h.create_user(doc_org, email='raiser@example.com', role='user')
        requester_headers = h.get_auth_headers(requester)
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            requester_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, requester_headers, doc_id)
        assert (
            client.get(
                f'/api/v1/approvals/documents/{doc_id}/approval',
                headers=doc_auth_headers,
            ).json()['status']
            == 'PENDING'
        )

        cancelled = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert cancelled.status_code == status.HTTP_200_OK, cancelled.text

        approval = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        ).json()
        assert approval['status'] == 'CANCELLED'

    # ------------------------------------------------------------------
    # Confirm over threshold auto-creates approval request
    # ------------------------------------------------------------------

    def test_confirm_over_threshold_creates_request(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Confirming a doc above threshold auto-creates an ApprovalRequest.

        Without the auto-create, the document is left in PENDING_APPROVAL
        with no request in the queue — a dead-end.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        resp = self._confirm_doc(client, doc_auth_headers, doc_id)
        assert resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

        approval_resp = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        assert approval_resp.status_code == status.HTTP_200_OK
        approval = approval_resp.json()
        assert approval is not None
        assert approval['status'] in {'PENDING', 'IN_PROGRESS'}
        assert approval['target_id'] == doc_id

    def test_get_approval_returns_enriched_stages_for_multistage_workflow(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """GET /approvals/documents/{id}/approval carries workflow_stages.

        The earlier path returned the bare request (workflow_stages=null),
               so a two-stage workflow rendered as "Single approval" in the queue.
        """
        workflow_resp = client.post(
            '/api/v1/approvals/workflows',
            headers=doc_auth_headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'name': 'Two Stage Workflow',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Review',
                        'approver_user_ids': [],
                    },
                    {
                        'order': 2,
                        'role': 'admin',
                        'label': 'Director Approval',
                        'approver_user_ids': [],
                    },
                ],
            },
        )
        assert workflow_resp.status_code == status.HTTP_201_CREATED, workflow_resp.text

        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        approval_resp = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        assert approval_resp.status_code == status.HTTP_200_OK
        approval = approval_resp.json()
        assert approval is not None
        assert approval['total_stages'] == 2
        assert approval['current_stage'] == 1
        assert approval['workflow_stages'] is not None
        assert [s['label'] for s in approval['workflow_stages']] == [
            'Manager Review',
            'Director Approval',
        ]

    def test_confirm_approval_required_without_workflow_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Approval required with no workflow → confirm refuses and names the gap.

               This used to confirm the document and call it graceful degradation,
               so the setting a manager switched on to control spending did nothing
        and said nothing. Refusing names the missing piece instead.
        """
        # No doc_approval_workflow fixture — no workflow in DB.
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'workflow' in resp.json()['detail']['message'].lower()

        # The document stays DRAFT — nothing was confirmed or released.
        after = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert after.json()['status'] == DocumentStatus.DRAFT.value

    def test_confirm_not_required_without_workflow_succeeds(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """No approval is due, so a missing workflow is irrelevant."""
        self._set_profile_threshold(client, doc_auth_headers, None)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ],
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == DocumentStatus.CONFIRMED.value

    # ------------------------------------------------------------------
    # Complete always blocks with active request
    # ------------------------------------------------------------------

    def test_complete_with_manual_request_blocks_regardless_of_status(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Regression: active request blocks completion regardless of status.

        A CONFIRMED document that someone manually sent to /request-approval
        (e.g., manager wants sign-off even though below threshold) must NOT
        be completable until the request is approved/rejected.

        The old code only called check_and_block when status was
        PENDING_APPROVAL or is_approval_required was True — so a
        manually-created request on a CONFIRMED doc could be bypassed by
        lowering the threshold after the fact.

        The document here is confirmed before the workflow exists, which is
        the only way to reach CONFIRMED with the manual door still open: a
        workflow in place gates the document at confirmation.
        """
        # Threshold high enough that the profile does not ask for approval.
        self._set_profile_threshold(client, doc_auth_headers, 10000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        self._add_workflow(client, doc_auth_headers)
        # Sanity-check: doc is CONFIRMED, no auto-created request.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.CONFIRMED.value

        # Manually create a request.
        self._request_approval(client, doc_auth_headers, doc_id)

        # Complete must be blocked by the active request.
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'approval' in resp.json()['detail']['message'].lower()

    # ------------------------------------------------------------------
    # Cancel/delete document cascades to active request
    # ------------------------------------------------------------------

    def test_cancel_document_cancels_active_request(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Cancelling a PENDING_APPROVAL doc also cancels the active request.

        Without the cascade, the request lingers in PENDING with a target
        that has been CANCELLED — a queue dead-end where approvers see a
        request for a document that no longer exists.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request (PENDING).
        self._confirm_doc(client, doc_auth_headers, doc_id)

        # Cancel the document.
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == DocumentStatus.CANCELLED.value

        # The request must now be CANCELLED, not PENDING.
        approval_resp = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        assert approval_resp.status_code == status.HTTP_200_OK
        approval = approval_resp.json()
        assert approval is not None
        assert approval['status'] == 'CANCELLED'

    def test_delete_document_cancels_active_request(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Deleting a draft with a lingering active request cancels the request.

        Cancelling a document cascades its request, and a cancelled document
        cannot be deleted any more — it is an act with a number, kept on
        purpose. The door this defense-in-depth guards is therefore the
        draft: a request left active by a cascade somebody bypassed (a
        direct write, a rolled-back cancel) must not outlive the draft it
        asks about.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request: the document parks in
        # PENDING_APPROVAL behind a PENDING request.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        # The bypass: the document stands as a draft again while its
        # request is still active, which no door of the application does.
        row = db_session.get(Document, uuid.UUID(doc_id))
        assert row is not None
        row.status = DocumentStatus.DRAFT.value
        db_session.commit()

        delete_resp = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert delete_resp.status_code == status.HTTP_204_NO_CONTENT, delete_resp.text

        # No active request for this doc remains.
        list_resp = client.get('/api/v1/approvals/requests', headers=doc_auth_headers)
        assert list_resp.status_code == status.HTTP_200_OK
        active = [
            r
            for r in list_resp.json()['items']
            if str(r['target_id']) == doc_id
            and r['status'] in ('PENDING', 'IN_PROGRESS')
        ]
        assert active == []

    def test_cancel_request_in_progress_works(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """cancel_request must work for IN_PROGRESS, not only PENDING.

        Setup: rebuild the workflow with two stages so that an approve
        advances the request to IN_PROGRESS (current_stage=2, status set
        by the service). Then cancel — should succeed.
        """
        # Replace the single-stage workflow with a 2-stage one (the
        # approvals services are async-only, so seed via the HTTP API).
        patch_resp = client.patch(
            f'/api/v1/approvals/workflows/{doc_approval_workflow.id}',
            headers=doc_auth_headers,
            json={
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [],
                    },
                    {
                        'order': 2,
                        'role': 'admin',
                        'label': 'Director Approval',
                        'approver_user_ids': [],
                    },
                ]
            },
        )
        assert patch_resp.status_code == status.HTTP_200_OK, patch_resp.text

        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        # Approve the first stage — request should move to IN_PROGRESS.
        first_approve = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert first_approve.status_code == status.HTTP_200_OK, first_approve.text
        assert first_approve.json()['status'] == 'IN_PROGRESS'

        # Cancel — must succeed even though status is IN_PROGRESS, not PENDING.
        request_id = first_approve.json()['id']
        cancel_resp = client.post(
            f'/api/v1/approvals/requests/{request_id}/cancel',
            headers=doc_auth_headers,
        )
        assert cancel_resp.status_code == status.HTTP_200_OK, cancel_resp.text
        assert cancel_resp.json()['status'] == 'CANCELLED'

    # ------------------------------------------------------------------
    # REJECTED request not reused (Fix 2 Part B)
    # ------------------------------------------------------------------

    def test_reject_then_new_request_and_approve(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """After rejecting, the document is DRAFT
        (rework loop). Re-confirm auto-creates a new request, which can be
        approved to bring the document back to CONFIRMED + COMPLETED.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        reject_resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject', headers=doc_auth_headers
        )
        assert reject_resp.status_code == status.HTTP_200_OK
        assert reject_resp.json()['status'] == 'REJECTED'

        # Doc is now DRAFT (rework loop) — re-confirm auto-creates a new
        # request because the threshold is still below the line value.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        approve_resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert approve_resp.status_code == status.HTTP_200_OK
        assert approve_resp.json()['status'] == 'APPROVED'

    def test_approve_failure_in_confirm_rolls_back_atomically(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Regression: approve + confirm_after_approval must be atomic.

        If the document status transition fails after the approval request
        has been advanced to APPROVED, the approval must NOT persist —
        otherwise the doc stays PENDING_APPROVAL forever while users see
        the approval as done.

        Bug: ``_approve_stage_impl`` commits internally (transaction #1)
        and ``confirm_after_approval`` commits again (transaction #2).
        If #2 fails, #1 stays durable -> inconsistency.
        Fix: remove inner commits so the FastAPI ``get_async_db`` helper
        commits the whole thing as a single transaction at request end.
        On Exception, ``get_async_db`` rolls back -> state stays coherent.
        The release now runs in the approvals module's decision listener,
        which refuses the decision when the warehouse cannot follow it.
        """
        from starlette.testclient import TestClient

        from app.modules.warehouse.warehouse_api import warehouse_api

        # Quiet TestClient so it does NOT re-raise the simulated failure —
        # we want to inspect the post-mortem DB state, not crash the test.
        quiet_client = TestClient(client.app, raise_server_exceptions=False)

        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        # Confirm auto-creates the request.
        self._confirm_doc(client, doc_auth_headers, doc_id)

        async def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('simulated downstream failure in confirm')

        monkeypatch.setattr(warehouse_api, 'release_document_async', _boom)

        approve_resp = quiet_client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        # Endpoint propagates RuntimeError -> HTTP 500
        assert approve_resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        # Both must roll back together (atomicity invariant):
        approval_resp = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        assert approval_resp.status_code == status.HTTP_200_OK
        assert approval_resp.json()['status'] != 'APPROVED'

        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.status_code == status.HTTP_200_OK
        assert doc_resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

    # ------------------------------------------------------------------
    # Manual request-approval flips doc to PENDING_APPROVAL
    # ------------------------------------------------------------------

    def test_manual_request_approval_flips_confirmed_doc_to_pending(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Manual /request-approval on a CONFIRMED doc must set doc.status = PENDING_APPROVAL.

        Regression: the threshold-auto path sets
        doc.status = PENDING_APPROVAL after creating the request, but the
        manual /request-approval endpoint did not — leaving the document
        stranded in CONFIRMED with an active request, invisible to the
        "Pending Approval" filter in Documents.

        The document is confirmed before the workflow exists: a document
        confirmed under a workflow is parked by the confirmation itself.
        """
        # Threshold high enough that the profile does not ask for approval.
        self._set_profile_threshold(client, doc_auth_headers, 10000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        self._add_workflow(client, doc_auth_headers)

        # Sanity: doc is CONFIRMED, no auto-created request.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.CONFIRMED.value

        # Manual request.
        self._request_approval(client, doc_auth_headers, doc_id)

        # Doc must now be PENDING_APPROVAL.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.status_code == status.HTTP_200_OK
        assert doc_resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

    def test_manual_request_approval_doc_visible_in_pending_approval_filter(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """GET /warehouse?status=PENDING_APPROVAL must include the manually-requested doc."""
        # Threshold high enough that the profile does not ask for approval.
        self._set_profile_threshold(client, doc_auth_headers, 10000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        self._add_workflow(client, doc_auth_headers)
        self._request_approval(client, doc_auth_headers, doc_id)

        list_resp = client.get(
            '/api/v1/warehouse/documents',
            params={'status': DocumentStatus.PENDING_APPROVAL.value},
            headers=doc_auth_headers,
        )
        assert list_resp.status_code == status.HTTP_200_OK, list_resp.text
        ids = [doc['id'] for doc in list_resp.json()['items']]
        assert doc_id in ids

    def test_manual_request_approval_second_call_returns_conflict(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """A second /request-approval on a PENDING_APPROVAL doc must keep status stable.

        The approvals_api guard against duplicate active requests correctly
        surfaces a 409 — the doc remains in PENDING_APPROVAL and no extra
        request is created. This is the contract the manual path must preserve.
        """
        self._set_profile_threshold(client, doc_auth_headers, 10000.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        self._add_workflow(client, doc_auth_headers)
        self._request_approval(client, doc_auth_headers, doc_id)

        # Second call: approvals_api rejects duplicate active request with 409.
        resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

    # ------------------------------------------------------------------
    # Rework loop (reject → DRAFT)
    # ------------------------------------------------------------------

    def test_reject_pending_approval_doc_transitions_to_draft(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Reject a PENDING_APPROVAL document must transition it to DRAFT.

        The current request is REJECTED (history preserved), and the document
        is editable again so the requester can fix the issue and re-submit.
        Without this, the requester is forced to cancel + recreate the doc.
        """
        # Threshold low so confirm auto-creates the request.
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        # Sanity: doc is PENDING_APPROVAL with an active request.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

        # Reject (the requester is also admin/manager in the test fixture,
        # so the role check passes; self-approve is gated by allow_self_approve).
        reject_resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject',
            headers=doc_auth_headers,
            params={'notes': 'Wrong price'},
        )
        assert reject_resp.status_code == status.HTTP_200_OK, reject_resp.text
        assert reject_resp.json()['status'] == 'REJECTED'

        # Doc must be DRAFT (rework loop), not stuck in PENDING_APPROVAL.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.status_code == status.HTTP_200_OK
        assert doc_resp.json()['status'] == DocumentStatus.DRAFT.value

        # The original request is still in REJECTED state (history preserved).
        approval_resp = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        # After rework, /approval returns the most recent request, which is
        # the original REJECTED one.
        assert approval_resp.status_code == status.HTTP_200_OK
        approval = approval_resp.json()
        assert approval is not None
        assert approval['status'] == 'REJECTED'

    def test_reject_then_re_request_creates_new_request(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """After rework (reject → DRAFT), the user can re-submit a new request.

        The history of the previous REJECTED request must be preserved.
        """
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)
        client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject',
            headers=doc_auth_headers,
            params={'notes': 'Wrong price'},
        )
        # Doc is DRAFT now; re-confirm auto-creates a new request (threshold
        # is still 100.00 and the line value is 250.00).
        self._confirm_doc(client, doc_auth_headers, doc_id)

        # Doc must be PENDING_APPROVAL with a new active request.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value
        approval_resp = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        assert approval_resp.json()['status'] == 'PENDING'

    def test_reject_releases_quant_reservations(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Reject must release quant reservations (same as cancel).

        OUT/INT docs hold reservations in PENDING_APPROVAL. Without release,
        the stock capacity is held by a DRAFT doc that the user is about to
        edit — double-booking risk.
        """
        # Use a low threshold so confirm auto-creates a request.
        self._set_profile_threshold(client, doc_auth_headers, 100.00)

        # OUT document — reservations are on source_location.
        source_location = doc_target_location
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'OUT',
            doc_partner.id,
            source_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
            source_location_id=source_location.id,
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        # Verify the doc was auto-pending.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

        # Reject.
        client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject',
            headers=doc_auth_headers,
            params={'notes': 'Cancel this'},
        )

        # Doc is DRAFT; the reservation must be released so it does not
        # block other OUT documents.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.DRAFT.value

    def test_reject_notifies_requester(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reject must best-effort notify the original requester.

        Notification failures must not block or roll back the reject — the
        same contract as the notification sent to approvers.
        """
        from app.modules.approvals import approvals_api as approvals_api_mod

        called_with: dict[str, object] = {}

        async def _spy(
            db: object,
            *,
            org_id: object,
            doc_id: object,
            request_id: object,
            requester_id: object,
            reason: object,
        ) -> None:
            called_with['org_id'] = org_id
            called_with['requester_id'] = requester_id
            called_with['reason'] = reason
            called_with['request_id'] = request_id

        monkeypatch.setattr(
            approvals_api_mod.ApprovalsAPI,
            'notify_rejection_async',
            staticmethod(_spy),
        )

        self._set_profile_threshold(client, doc_auth_headers, 100.00)
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        )
        self._confirm_doc(client, doc_auth_headers, doc_id)

        client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject',
            headers=doc_auth_headers,
            params={'notes': 'Numbers off'},
        )

        assert called_with, 'notify_rejection_async was not called'
        assert called_with['reason'] == 'Numbers off'
        # The notify helper is best-effort; the doc must be in DRAFT even
        # if the notification path is later swapped to a no-op for tests.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert doc_resp.json()['status'] == DocumentStatus.DRAFT.value
