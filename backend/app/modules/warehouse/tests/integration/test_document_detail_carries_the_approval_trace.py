"""The document detail names the hands behind it, each for their own act.

A document that went through approval has two hands on it: the one that
confirmed it and sent it into the queue, and the one that approved it.
The detail used to keep only one -- the approval overwrote the
confirmation -- so the card named the approver as the confirmer and the
person who actually confirmed the document disappeared. The approval
decisions travel with their approver now, and the confirmation keeps its
author through the whole workflow.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.approvals.models import ApprovalDecision, ApprovalWorkflow
from app.modules.warehouse.models import Document


def _detail(client: TestClient, headers: dict[str, str], doc_id: str) -> dict[str, Any]:
    resp = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    detail: dict[str, Any] = resp.json()
    return detail


@pytest.mark.integration
class TestDocumentDetailCarriesTheApprovalTrace:
    @staticmethod
    def _draft(
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> str:
        resp = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        profile = resp.json()
        put = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={
                **{
                    k: v
                    for k, v in profile.items()
                    if k not in ('id', 'organization_id', 'created_at', 'updated_at')
                },
                'approval_threshold': '100.00',
                'approval_required_for_types': [],
                'value_tracking_enabled': True,
            },
        )
        assert put.status_code == status.HTTP_200_OK, put.text

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                        'unit_price': '50.00',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        return str(created.json()['id'])

    def test_the_detail_names_the_confirmer_and_the_approver_separately(
        self,
        h: ModuleTestHelper,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_user: User,
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_org: Organization,
    ) -> None:
        doc_id = self._draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        waiting = _detail(client, doc_auth_headers, doc_id)
        assert waiting['status'] == 'PENDING_APPROVAL'
        trace = waiting['approval']
        assert trace is not None
        assert trace['status'] == 'PENDING'
        # When the question was asked -- the rung the timeline marks while
        # the document waits. A stage row may already exist; it carries no
        # decision time until somebody decides.
        assert trace['created_at'] is not None
        # Waiting for approval is not unconfirmed: the person who confirmed
        # the document and sent it into the queue is named from the start.
        assert waiting['confirmed_by'] == str(doc_user.id)
        assert waiting['confirmed_at'] is not None
        assert all(decision['decided_at'] is None for decision in trace['decisions'])

        approver = h.create_user(doc_org, email='approver@example.com')
        approve = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve',
            headers=h.get_auth_headers(approver),
        )
        assert approve.status_code == status.HTTP_200_OK, approve.text

        decided = _detail(client, doc_auth_headers, doc_id)
        assert decided['status'] == 'CONFIRMED'
        trace = decided['approval']
        assert trace is not None
        assert trace['status'] == 'APPROVED'
        assert len(trace['decisions']) == 1
        decision = trace['decisions'][0]
        assert decision['status'] == 'APPROVED'
        assert decision['decided_at'] is not None
        # The approval is named, separately from the confirmation: the
        # approver decided on their own hand, at the decision's own moment.
        assert decision['decided_by'] == str(approver.id)
        assert decision['decided_by_name']
        # The confirmation survived the approval, with its author.
        assert decided['confirmed_by'] == str(doc_user.id)
        assert decided['confirmed_by_name'] == doc_user.full_name
        assert decided['confirmed_by_name'] != decision['decided_by_name']

    def test_a_two_stage_trace_keeps_stage_order_whatever_the_table_holds(
        self,
        h: ModuleTestHelper,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_org: Organization,
    ) -> None:
        """The card's decisions follow the workflow, not the table's history.

        A stage row is updated when its stage decides, and the new version
        lands wherever the page has room, so the table can hold the final
        stage before the first. The card reads the last approving decision
        as "approved by"; from a trace in table order a two-stage approval
        named the first stage's approver.
        """
        doc_approval_workflow.stages = [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Manager Approval',
                'approver_user_ids': [],
            },
            {
                'order': 2,
                'role': 'admin',
                'label': 'Director Confirmation',
                'approver_user_ids': [],
            },
        ]
        db_session.commit()

        doc_id = self._draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        first = h.create_user(doc_org, email='trace-first@example.com')
        final = h.create_user(doc_org, email='trace-final@example.com')
        for approver in (first, final):
            approve = client.post(
                f'/api/v1/approvals/documents/{doc_id}/approve',
                headers=h.get_auth_headers(approver),
            )
            assert approve.status_code == status.HTTP_200_OK, approve.text

        approved = _detail(client, doc_auth_headers, doc_id)
        assert approved['status'] == 'CONFIRMED'
        request_id = UUID(approved['approval']['request_id'])

        # Keep the decided rows as the API wrote them, then write them back
        # in reverse stage order. The relation is rebuilt so the physical
        # order is certain: the read below must get stage order from its own
        # query, not from the heap.
        rows = [
            (row.stage_order, row.approver_id, row.status, row.notes, row.decided_at)
            for row in db_session.query(ApprovalDecision)
            .filter(ApprovalDecision.approval_request_id == request_id)
            .order_by(ApprovalDecision.stage_order)
            .all()
        ]
        assert [row[0] for row in rows] == [1, 2]
        db_session.execute(text('TRUNCATE approval_decisions'))
        db_session.flush()
        for stage_order, approver_id, row_status, notes, decided_at in reversed(rows):
            db_session.add(
                ApprovalDecision(
                    approval_request_id=request_id,
                    stage_order=stage_order,
                    approver_id=approver_id,
                    status=row_status,
                    notes=notes,
                    decided_at=decided_at,
                )
            )
            db_session.flush()
        db_session.commit()

        reordered = _detail(client, doc_auth_headers, doc_id)
        decisions = reordered['approval']['decisions']
        assert [decision['decided_by'] for decision in decisions] == [
            str(first.id),
            str(final.id),
        ]
        # The card's "approved by" reads the last approving decision, so the
        # final stage's approver is the one it names.
        assert decisions[-1]['decided_by_name'] == final.full_name

    @pytest.mark.parametrize('document_status', ['CONFIRMED', 'COMPLETED', 'CANCELLED'])
    @pytest.mark.parametrize('trailing_self_stage', [False, True])
    def test_legacy_approval_recovers_the_confirmer_from_the_journal(
        self,
        h: ModuleTestHelper,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_user: User,
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_org: Organization,
        document_status: str,
        trailing_self_stage: bool,
    ) -> None:
        if trailing_self_stage:
            doc_approval_workflow.stages = [
                *doc_approval_workflow.stages,
                {
                    'order': 2,
                    'role': 'manager',
                    'label': 'Requester stage',
                    'approver_user_ids': [str(doc_user.id)],
                },
            ]
            db_session.commit()
        doc_id = self._draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        approver = h.create_user(doc_org, email='legacy-approver@example.com')
        approve = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve',
            headers=h.get_auth_headers(approver),
        )
        assert approve.status_code == status.HTTP_200_OK, approve.text

        # Reproduce the persisted shape the old approval code wrote. The
        # journal still holds the original confirmation by a different hand.
        document = db_session.get(Document, UUID(doc_id))
        assert document is not None
        document.confirmed_by = approver.id
        document.confirmed_at = datetime.now(UTC)
        document.status = document_status
        # A busy record must not lose its confirmer beyond the first page.
        db_session.add_all(
            [
                AuditLog(
                    organization_id=doc_org.id,
                    user_id=approver.id,
                    action='UPDATE',
                    target_type='document',
                    target_id=document.id,
                    snapshot={'notes': 'Later edit'},
                    created_at=document.confirmed_at,
                )
                for _ in range(101)
            ]
        )
        db_session.commit()

        detail = _detail(client, doc_auth_headers, doc_id)
        assert detail['confirmed_by'] == str(doc_user.id)
        assert detail['confirmed_by_name'] == doc_user.full_name
        decision = detail['approval']['decisions'][0]
        assert detail['confirmed_at'] < decision['decided_at']
        assert decision['decided_by'] == str(approver.id)
        # Enrichment is read-only: it does not silently rewrite old rows.
        db_session.refresh(document)
        assert document.confirmed_by == approver.id

        # A real confirmation after the approval takes precedence over the
        # historical one, even when the approver is also the new confirmer.
        document.confirmed_at = datetime.now(UTC) + timedelta(seconds=1)
        later_stamp = document.confirmed_at.isoformat()
        db_session.add(
            AuditLog(
                organization_id=doc_org.id,
                user_id=approver.id,
                action='UPDATE',
                target_type='document',
                target_id=document.id,
                snapshot={'new_status': 'CONFIRMED', 'requires_approval': False},
                created_at=document.confirmed_at,
            )
        )
        db_session.commit()
        later = _detail(client, doc_auth_headers, doc_id)
        assert later['confirmed_by'] == str(approver.id)
        assert datetime.fromisoformat(later['confirmed_at']) == datetime.fromisoformat(
            later_stamp
        )

    def test_a_withdrawn_request_keeps_the_confirmation_it_carried(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_org: Organization,
    ) -> None:
        doc_id = self._draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        waiting = _detail(client, doc_auth_headers, doc_id)
        cancel = client.post(
            f'/api/v1/approvals/requests/{waiting["approval"]["request_id"]}/cancel',
            headers=doc_auth_headers,
        )
        assert cancel.status_code == status.HTTP_200_OK, cancel.text
        withdrawn = _detail(client, doc_auth_headers, doc_id)
        # Withdrawing takes back the question, not the confirmation that
        # asked it: the document stands confirmed, with its author named.
        assert withdrawn['status'] == 'CONFIRMED'
        assert withdrawn['confirmed_at'] is not None
        assert withdrawn['confirmed_by'] == waiting['confirmed_by']
        assert withdrawn['confirmed_by_name'] is not None

    def test_a_rejected_document_carries_no_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_org: Organization,
    ) -> None:
        doc_id = self._draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        reject = client.post(
            f'/api/v1/approvals/documents/{doc_id}/reject', headers=doc_auth_headers
        )
        assert reject.status_code == status.HTTP_200_OK, reject.text
        rejected = _detail(client, doc_auth_headers, doc_id)
        assert rejected['approval']['status'] == 'REJECTED'
        assert rejected['status'] == 'DRAFT'
        # Back to draft for rework: the confirmation it carried was undone
        # with the rejection, so the card names nobody.
        assert rejected['confirmed_at'] is None
        assert rejected['confirmed_by'] is None

    def test_a_manually_requested_approval_keeps_the_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_org: Organization,
    ) -> None:
        doc_id = self._draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        profile = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        body = {
            k: v
            for k, v in profile.json().items()
            if k not in ('id', 'organization_id', 'created_at', 'updated_at')
        }
        # Above the document's value: confirming does not queue it.
        put = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={**body, 'approval_threshold': '100000.00'},
        )
        assert put.status_code == status.HTTP_200_OK, put.text
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        confirmed = _detail(client, doc_auth_headers, doc_id)
        assert confirmed['status'] == 'CONFIRMED'
        assert confirmed['confirmed_at'] is not None

        requested = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=doc_auth_headers,
        )
        assert requested.status_code == status.HTTP_200_OK, requested.text
        waiting = _detail(client, doc_auth_headers, doc_id)
        assert waiting['status'] == 'PENDING_APPROVAL'
        # Asking for an approval on top of a confirmed document does not
        # un-confirm it.
        assert waiting['confirmed_by'] == confirmed['confirmed_by']
        assert waiting['confirmed_at'] == confirmed['confirmed_at']
