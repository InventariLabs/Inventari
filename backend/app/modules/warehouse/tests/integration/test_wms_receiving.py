"""
Integration tests for WMS Receiving Workflow.

Tests verify:
- Start receiving session for CONFIRMED IN/PZ documents
- Scan receive by barcode matches document line and increments quantity
- Unmatched barcode rejected
- Short receive with discrepancy
- Undo receive
- Skip receive line
- Complete receive session updates DocumentLine.done_quantity
- Cancel receive session restores state
- OUT document rejected for receiving
"""

import re
import uuid
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import sow as _sow


def _create_in_document(
    client: TestClient,
    auth_headers: dict[str, str],
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    quantity: int = 10,
) -> str:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=auth_headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(str, response.json()['id'])


def _confirm_document(
    client: TestClient, auth_headers: dict[str, str], doc_id: str
) -> None:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm',
        headers=auth_headers,
    )
    assert resp.status_code == status.HTTP_200_OK


def _add_document_workflow(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Put an active document workflow in place mid-test.

    A document confirmed before the workflow exists is the one way to reach
    CONFIRMED with the request door still open, now that an active workflow
    gates confirmation as well as execution.
    """
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=auth_headers,
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'is_active': True,
            'expected_scope': {'holds': 'all'},
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


@pytest.mark.integration
class TestWmsReceiveStart:
    def test_start_receive_session_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['status'] == 'active'
        assert data['document_id'] == doc_id
        assert data['total_lines'] >= 1
        assert data['pending_lines'] >= 1
        assert data['received_lines'] == 0

    def test_start_receive_draft_document_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_receive_out_document_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        doc_id = response.json()['id']
        _confirm_document(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_receive_hands_back_the_session_already_open(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp1 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp1.status_code == status.HTTP_201_CREATED

        # The twin of the picking case: their own open session comes back,
        # rather than a refusal with nowhere to go from it.
        resp2 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp2.status_code == status.HTTP_201_CREATED
        assert resp2.json()['id'] == resp1.json()['id']

    def test_start_receive_names_the_holder_and_the_release_works(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """A held document is never out of reach for the next reader.

        Closing a sheet no longer cancels the session, so a
        colleague can meet the refusal. It must name the holder and carry
        the session id, and the document's own release door must accept the
        colleague's hand — otherwise one closed tab locks the document for
        everyone but its owner.
        """
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp1 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp1.status_code == status.HTTP_201_CREATED
        held_session_id = resp1.json()['id']

        user2 = h.create_user(doc_org, email='receiver2@example.com')
        headers2 = h.get_auth_headers(user2)

        resp2 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=headers2,
        )
        assert resp2.status_code == status.HTTP_409_CONFLICT
        detail = resp2.json()['detail']
        assert detail['code'] == 'SESSION_HELD_BY_OTHER_USER'
        assert detail['held_session_id'] == held_session_id
        assert isinstance(detail['held_by'], str) and detail['held_by']

        # The escape goes through the release door, not the holder's cancel.
        cancel = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{held_session_id}/release',
            headers=headers2,
        )
        assert cancel.status_code == status.HTTP_204_NO_CONTENT

        resp3 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=headers2,
        )
        assert resp3.status_code == status.HTTP_201_CREATED
        assert resp3.json()['id'] != held_session_id

    def test_start_receive_blocked_when_approval_pending(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A document waiting for an approval asked for by hand cannot be scanned.

        The request holds the document — it waits in PENDING_APPROVAL for the
        approvals module — and a session starts only on a CONFIRMED one, so
        the hold is the gate. The document is confirmed before the workflow
        exists, because a workflow in place gates the confirmation itself.
        """
        from app.modules.warehouse.models import Document

        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        _add_document_workflow(client, doc_auth_headers)

        request_resp = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=doc_auth_headers,
        )
        assert request_resp.status_code == status.HTTP_200_OK

        doc = db_session.scalar(
            select(Document).where(Document.id == uuid.UUID(doc_id))
        )
        assert doc is not None
        assert doc.status == 'PENDING_APPROVAL'
        assert doc.held_by == 'approvals'

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text


@pytest.mark.integration
class TestWmsReceiveScan:
    def test_scan_receive_matches_document_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '3'},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'received'
        assert data['received_quantity'] == 3.0
        assert data['expected_quantity'] == 10.0
        assert data['session_complete'] is False

    def test_scan_receive_reaches_expected_completes_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '5'},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['session_complete'] is True

        # resolving the last line must close the session, not leave it
        # active — an active session blocks the document forever.
        get_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}',
            headers=doc_auth_headers,
        )
        assert get_resp.status_code == status.HTTP_200_OK
        assert get_resp.json()['status'] == 'completed'
        assert get_resp.json()['completed_at'] is not None

    def test_complete_document_after_auto_closed_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """an auto-closed session must not block the document — the
        complete endpoint used to be guarded only for picking in tests."""
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        scan = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '5'},
        )
        assert scan.status_code == status.HTTP_200_OK
        assert scan.json()['session_complete'] is True

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        assert complete.json()['status'] == 'COMPLETED'

    def test_scan_receive_matches_line_by_barcode_without_template_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """lines created from the UI carry no product_template_id.

        The scan matcher must fall back to the barcode stored on the document
        line, otherwise a receipt created from the catalog picker can never be
        received.
        """
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'name': doc_template.name,
                        'barcode': doc_template.barcode,
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        doc_id = response.json()['id']
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '10'},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'received'
        assert data['received_quantity'] == 10.0
        assert data['session_complete'] is True

    def test_scan_receive_rejects_unmatched_barcode(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        h: ModuleTestHelper,
    ) -> None:
        other_template = h.create_template(
            doc_org, name='Other Product', barcode='9999999999999'
        )

        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': other_template.barcode, 'quantity': '1'},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'not_in_document'

    def test_scan_receive_refuses_over_quantity_without_the_permission(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """A receiver without the over-receipt permission stops at the tolerance.

        The default tolerance is 0, so five against an expected three is
        refused — and the refusal says whose hand is needed.
        """
        receiver = h.create_user(
            doc_org, email='plain-receiver@example.com', role='user'
        )
        h.grant_permissions(receiver, ['warehouse:read', 'warehouse:write'])
        receiver_headers = h.get_auth_headers(receiver)

        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=3,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=receiver_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=receiver_headers,
            json={'barcode': doc_template.barcode, 'quantity': '5'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'over-receipt tolerance' in resp.text

    def test_scan_receive_unknown_barcode(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': 'UNKNOWN_BARCODE_12345', 'quantity': '1'},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'not_found'

    def test_scan_receive_incremental(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp1 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '3'},
        )
        assert resp1.json()['received_quantity'] == 3.0

        resp2 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '4'},
        )
        assert resp2.json()['received_quantity'] == 7.0

        resp3 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '3'},
        )
        assert resp3.json()['received_quantity'] == 10.0
        assert resp3.json()['session_complete'] is True


@pytest.mark.integration
class TestWmsReceiveShort:
    def test_short_receive_with_discrepancy(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'received_quantity': '7',
                'discrepancy_code': 'DAMAGE',
                'discrepancy_reason': '3 units damaged in transit',
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'short_receive_confirmed'
        assert data['received_quantity'] == 7.0
        assert data['expected_quantity'] == 10.0

    def test_the_held_part_is_recorded_on_the_document_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The floor can say part of the count is damaged, not only that it is missing.

        Seven arrived, three of them are held back: the document line has to
        carry both numbers, because the count alone would either quarantine
        goods that were fine or release goods that were not.
        """
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'received_quantity': '7',
                'held_quantity': '3',
                'discrepancy_code': 'DAMAGE',
                'discrepancy_reason': 'Three crushed boxes',
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        line = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()['lines'][0]
        assert line['held_quantity'] == '3.000'
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}',
            headers=doc_auth_headers,
        ).json()
        assert session['lines'][0]['held_quantity'] == 3.0
        # The row has to say why the three are held, not only that they are.
        assert session['lines'][0]['discrepancy_code'] == 'DAMAGE'

    def test_a_held_quantity_above_the_count_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'received_quantity': '7',
                'held_quantity': '8',
                'discrepancy_code': 'DAMAGE',
            },
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_a_held_quantity_under_another_code_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'received_quantity': '7',
                'held_quantity': '3',
                'discrepancy_code': 'SHORTAGE',
            },
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_zero_received_is_recorded(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Nothing arrived is a quantity this door accepts.

        The floor used to be the figure itself, so a line checked and found
        empty could only be skipped — "we looked at it and nothing came" and
        "we never looked" were the same record.
        """
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={'line_id': line_id, 'received_quantity': '0'},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'short_receive_confirmed'
        assert data['received_quantity'] == 0.0
        assert data['expected_quantity'] == 10.0


@pytest.mark.integration
class TestWmsReceiveUndo:
    def test_undo_receive_resets_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '5'},
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/undo',
            headers=doc_auth_headers,
            params={'line_id': str(line_id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['line_id'] == line_id
        assert data['restored_quantity'] == 0


@pytest.mark.integration
class TestWmsReceiveSkip:
    def test_skip_receive_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/skip',
            headers=doc_auth_headers,
            params={'line_id': str(line_id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'skipped'
        assert resp.json()['session_complete'] is True


@pytest.mark.integration
class TestWmsReceiveComplete:
    def test_complete_receive_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '5'},
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/complete',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'completed'

    def test_complete_with_pending_lines_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/complete',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


#: A refusal that carries no identifier, checked by the tests that pin one:
#: the raw session id meant nothing to the reader the sentence is written for.
_UUID_IN_TEXT = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE
)


@pytest.mark.integration
class TestTheRefusalWhileAReceivingSessionIsOpen:
    """What the document's own completion and cancellation say while
    receiving runs.

    The sentence came from picking's vocabulary whatever the session was —
    the worker was told to end a picking session over a receiving one — and
    it carried the raw session id, a number the document page never shows.
    """

    def test_complete_and_cancel_name_the_receiving_session_and_carry_no_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED
        session_id = start.json()['id']

        for action in ('complete', 'cancel'):
            resp = client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/{action}',
                headers=doc_auth_headers,
            )
            assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
            detail = resp.json()['detail']
            assert detail['code'] == 'WMS_SESSION_ACTIVE'
            msg = detail['message']
            assert 'receiving session' in msg.lower(), msg
            assert 'picking session' not in msg.lower(), msg
            assert _UUID_IN_TEXT.search(msg) is None, msg
            assert session_id not in msg


@pytest.mark.integration
class TestWmsReceiveCancel:
    def test_cancel_receive_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '3'},
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/cancel',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.integration
class TestWmsReceiveListAndGet:
    def test_list_receive_sessions(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )

        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()['items']
        assert len(data) >= 1
        assert data[0]['document_id'] == doc_id

    def test_get_receive_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['id'] == session_id


@pytest.mark.integration
class TestWmsReceiveShortStatus:
    def test_short_receive_session_status(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Receiving session with short line → status='short_receive'."""
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        # Short-receive 7 out of 10
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={
                'line_id': line_id,
                'received_quantity': '7',
                'discrepancy_code': 'DAMAGE',
                'discrepancy_reason': '3 damaged',
            },
        )

        # resolving the last line via short-receive closes the session
        # immediately; the explicit complete endpoint is then idempotent.
        get_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}',
            headers=doc_auth_headers,
        )
        assert get_resp.status_code == status.HTTP_200_OK
        assert get_resp.json()['status'] == 'short_receive'
        assert get_resp.json()['completed_at'] is not None

        # Complete the session
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/complete',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'short_receive'


@pytest.mark.integration
class TestTheReceivingSessionSpeaksOneVocabulary:
    """A line reloaded says what it said before the page was reloaded.

    Receiving reuses the picking machinery down to the table name, so a full
    receipt is stored as ``picked``. The receiving contract has never had
    that word — its screen, its summary and its label map are all written
    against ``received`` — so a session read back after a refresh showed a
    received line as pending, with the buttons to receive it a second time.
    """

    def test_a_received_line_reads_as_received_after_a_reload(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '5'},
        )

        reloaded = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}',
            headers=doc_auth_headers,
        )

        assert reloaded.status_code == status.HTTP_200_OK
        body = reloaded.json()
        line = body['lines'][0]
        assert line['status'] == 'received'
        assert line['received_quantity'] == 5
        # The counters and the line have to agree; the summary counts one
        # and the list renders the other.
        assert body['received_lines'] == 1
        assert body['pending_lines'] == 0

    def test_a_short_receive_still_reads_as_short(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={'line_id': line_id, 'received_quantity': '2'},
        )

        reloaded = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}',
            headers=doc_auth_headers,
        )

        assert reloaded.json()['lines'][0]['status'] == 'short'


@pytest.mark.integration
class TestWmsReceiveSessionIsOwnedByItsOpener:
    """A session belongs to the receiver who opened it.

    A colleague holding ``warehouse:write`` could work someone else's
    session through the raw API. The refusal is the same held-session
    envelope ``start`` already answers with, so the release dialog reads it
    unchanged; the release itself stays the release door's job.
    """

    def test_a_foreign_receiver_is_refused_by_every_operation(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        foreign = h.create_user(doc_org, email='receiver-foreign@example.com')
        foreign_headers = h.get_auth_headers(foreign)

        operations: list[tuple[str, dict[str, Any]]] = [
            (
                'scan',
                {'json': {'barcode': doc_template.barcode, 'quantity': '1'}},
            ),
            (
                'short-receive',
                {'json': {'line_id': line_id, 'received_quantity': '1'}},
            ),
            ('undo', {'params': {'line_id': line_id}}),
            ('skip', {'params': {'line_id': line_id}}),
            ('complete', {}),
            ('cancel', {}),
        ]
        for operation, kwargs in operations:
            resp = client.post(
                f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/{operation}',
                headers=foreign_headers,
                **kwargs,
            )
            assert resp.status_code == status.HTTP_409_CONFLICT, (
                operation,
                resp.text,
            )
            detail = resp.json()['detail']
            assert detail['code'] == 'SESSION_HELD_BY_OTHER_USER', operation
            assert detail['held_session_id'] == session_id, operation

        # Nothing the foreign hand tried left a mark: the session's owner
        # still works the same line.
        own = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '5'},
        )
        assert own.status_code == status.HTTP_200_OK, own.text
        assert own.json()['session_complete'] is True


@pytest.mark.integration
class TestWmsReceiveSessionUnderTheWrongDocument:
    """The document in the URL scopes the session id, for every door.

    The service found a session by id alone, so a session quoted under
    another document's URL was worked — on a document the URL never named.
    Both ids travel together; when they disagree the session is not there.
    """

    def test_every_operation_is_not_found_under_another_documents_url(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_a = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        doc_b = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_a)
        _confirm_document(client, doc_auth_headers, doc_b)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_a}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED
        session_id = start.json()['id']
        line_id = start.json()['lines'][0]['id']

        operations: list[tuple[str, dict[str, Any]]] = [
            (
                'scan',
                {'json': {'barcode': doc_template.barcode, 'quantity': '1'}},
            ),
            (
                'short-receive',
                {'json': {'line_id': line_id, 'received_quantity': '1'}},
            ),
            ('undo', {'params': {'line_id': line_id}}),
            ('skip', {'params': {'line_id': line_id}}),
            ('complete', {}),
            ('cancel', {}),
        ]
        for operation, kwargs in operations:
            resp = client.post(
                f'/api/v1/warehouse/documents/{doc_b}/receiving/{session_id}/{operation}',
                headers=doc_auth_headers,
                **kwargs,
            )
            assert resp.status_code == status.HTTP_404_NOT_FOUND, (
                operation,
                resp.text,
            )
            assert resp.json()['detail']['code'] == 'RECEIVING_SESSION_NOT_FOUND', (
                operation
            )

        # The session is still the one doc_a opened, and still active.
        under_its_own = client.get(
            f'/api/v1/warehouse/documents/{doc_a}/receiving/{session_id}',
            headers=doc_auth_headers,
        )
        assert under_its_own.status_code == status.HTTP_200_OK
        assert under_its_own.json()['status'] == 'active'

    def test_the_read_is_not_found_under_another_documents_url(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_a = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        doc_b = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=5,
        )
        _confirm_document(client, doc_auth_headers, doc_a)
        _confirm_document(client, doc_auth_headers, doc_b)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_a}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED

        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_b}/receiving/{start.json()["id"]}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()['detail']['code'] == 'RECEIVING_SESSION_NOT_FOUND'
