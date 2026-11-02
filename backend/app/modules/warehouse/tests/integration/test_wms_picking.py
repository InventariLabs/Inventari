"""
Integration tests for WMS Picking Workflow.

Tests verify:
- Start picking session for CONFIRMED OUT/INT documents
- Scan pick by barcode (a scan without one is refused)
- Short pick with discrepancy
- Undo pick
- Skip pick line
- Complete pick session updates DocumentLine.done_quantity
- Cancel pick session restores state
- Full flow: CONFIRMED → pick → complete → document COMPLETED
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

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import (
    WmsPickLine,
    WmsPickSession,
)
from app.modules.warehouse.tests.integration._records import (
    shelf_quant as _shelf_quant,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)

#: A refusal that carries no identifier, checked by the tests that pin one:
#: the raw session id meant nothing to the reader the sentence is written for.
_UUID_IN_TEXT = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE
)


def _create_out_document(
    client: TestClient,
    auth_headers: dict[str, str],
    source_location_id: uuid.UUID,
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: int = 5,
) -> str:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=auth_headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'item_id': str(item_id),
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
class TestWmsPickStart:
    def test_start_pick_session_success(
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
            '20',
        )
        doc_source_location.short_code = 'SRC-01'
        db_session.commit()

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['status'] == 'active'
        assert data['document_id'] == doc_id
        assert data['total_lines'] >= 1
        # The floor card reads the label's code large and the name under it.
        (line,) = data['lines']
        assert line['location_id'] == str(doc_source_location.id)
        assert line['location_code'] == 'SRC-01'
        assert line['location_name'] == 'Source Warehouse'

    def test_start_pick_draft_document_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_pick_blocked_when_approval_pending(
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
        """A document waiting for an approval asked for by hand cannot be scanned.

        The request holds the document — it waits in PENDING_APPROVAL for the
        approvals module — and a session starts only on a CONFIRMED one, so
        the hold is the gate. The document is confirmed before the workflow
        exists, because a workflow in place gates the confirmation itself.
        """
        from app.modules.warehouse.models import Document

        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
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
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_start_pick_hands_back_the_session_already_open(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp1 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp1.status_code == status.HTTP_201_CREATED

        # A second tap on the same button used to refuse, and nothing in the
        # interface could reach the session that was already open — the
        # document could then be neither completed nor cancelled. The picker
        # gets their own session back instead, on the lines already picked.
        resp2 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp2.status_code == status.HTTP_201_CREATED
        assert resp2.json()['id'] == resp1.json()['id']

    def test_start_pick_names_the_holder_and_the_release_works(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The picking twin of the receiving release: the refusal names the
        holder and carries the session id, and the colleague can put the
        held session back and start their own."""
        # The stock goes up the way the application puts it there: a record
        # through the items door, whose bridge writes the movement.
        stocked = client.post(
            '/api/v1/items',
            headers=doc_auth_headers,
            json={
                'name': doc_template.name,
                'barcode': doc_template.barcode,
                'location_id': str(doc_source_location.id),
                'quantity': 20,
            },
        )
        assert stocked.status_code == status.HTTP_201_CREATED, stocked.text
        item_id = stocked.json()['id']

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            item_id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp1 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp1.status_code == status.HTTP_201_CREATED
        held_session_id = resp1.json()['id']

        user2 = h.create_user(doc_org, email='picker2@example.com')
        headers2 = h.get_auth_headers(user2)

        resp2 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=headers2,
        )
        assert resp2.status_code == status.HTTP_409_CONFLICT
        detail = resp2.json()['detail']
        assert detail['code'] == 'SESSION_HELD_BY_OTHER_USER'
        assert detail['held_session_id'] == held_session_id
        assert isinstance(detail['held_by'], str) and detail['held_by']

        cancel = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{held_session_id}/release',
            headers=headers2,
        )
        assert cancel.status_code == status.HTTP_204_NO_CONTENT

        resp3 = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=headers2,
        )
        assert resp3.status_code == status.HTTP_201_CREATED
        assert resp3.json()['id'] != held_session_id


@pytest.mark.integration
class TestWmsPickScan:
    def test_scan_pick_by_barcode(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'picked'
        assert data['picked_quantity'] == 5.0
        assert data['session_complete'] is True

    def test_scan_pick_without_a_barcode_is_refused(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        pick_line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == session_id)
        ).first()
        assert pick_line is not None

        # The scan is by barcode only: a scan that names none has nothing
        # to match a line on, and picks nothing.
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'quantity': 5},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        db_session.expire_all()
        db_session.refresh(pick_line)
        assert pick_line.picked_quantity == 0

    def test_scan_pick_moves_only_the_declared_quantity(
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
        """One scan of one unit closes one unit, not the whole line.

        Scanning a single piece out of four used to answer
        ``picked_quantity: 4`` and close the line -- the picker had no way
        to report what was actually in their hand.
        """
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        first = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )
        assert first.status_code == status.HTTP_200_OK
        data = first.json()
        assert data['status'] == 'picked'
        assert data['picked_quantity'] == 2.0
        assert data['expected_quantity'] == 5.0
        assert data['session_complete'] is False

        lines = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}',
            headers=doc_auth_headers,
        ).json()['lines']
        assert lines[0]['status'] == 'pending'
        assert lines[0]['picked_quantity'] == 2.0

        second = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 3},
        )
        assert second.json()['picked_quantity'] == 5.0
        assert second.json()['session_complete'] is True

    def test_scan_pick_without_quantity_takes_one(
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
        """Same default as receiving: a scan with no quantity means one."""
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode},
        )
        assert resp.json()['picked_quantity'] == 1.0
        assert resp.json()['session_complete'] is False

    def test_scan_pick_refuses_more_than_expected(
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
        """Over-picking answers `over_quantity` and changes nothing."""
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 6},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'over_quantity'

        lines = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}',
            headers=doc_auth_headers,
        ).json()['lines']
        assert lines[0]['status'] == 'pending'
        assert lines[0]['picked_quantity'] == 0.0

    def test_scan_unknown_barcode(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': 'UNKNOWN-BARCODE-999'},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'not_found'


@pytest.mark.integration
class TestWmsPickShort:
    def test_short_pick_confirms_partial(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
            quantity=10,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        pick_line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == session_id)
        ).first()
        assert pick_line is not None

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/short-pick',
            headers=doc_auth_headers,
            json={
                'line_id': str(pick_line.id),
                'picked_quantity': 3,
                'discrepancy_code': 'SHORTAGE',
                'discrepancy_reason': 'Only 3 found on shelf',
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'short_pick_confirmed'
        assert data['picked_quantity'] == 3.0
        assert data['expected_quantity'] == 10.0


@pytest.mark.integration
class TestWmsPickUndo:
    def test_undo_pick_restores_pending(
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
            '20',
        )

        # Two lines on purpose: resolving the last one ends the session, and
        # a finished session takes no more instructions. Undo belongs to a
        # session still in progress, which is also the only moment the sheet
        # offers it.
        create = client.post(
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
                    },
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 3,
                    },
                ],
            },
        )
        assert create.status_code == status.HTTP_201_CREATED
        doc_id = create.json()['id']
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )

        pick_line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == session_id,
                WmsPickLine.status == 'picked',
            )
        ).first()
        assert pick_line is not None

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/undo',
            headers=doc_auth_headers,
            params={'line_id': str(pick_line.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['line_id'] == str(pick_line.id)


@pytest.mark.integration
class TestWmsPickSkip:
    def test_skip_line(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        pick_line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == session_id,
                WmsPickLine.status == 'pending',
            )
        ).first()
        assert pick_line is not None

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/skip',
            headers=doc_auth_headers,
            params={'line_id': str(pick_line.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'skipped'


@pytest.mark.integration
class TestWmsPickComplete:
    def test_complete_session_after_all_picked(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/complete',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'completed'


@pytest.mark.integration
class TestWmsPickCancel:
    def test_cancel_session_restores_lines(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/cancel',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        session = db_session.scalars(
            select(WmsPickSession).where(WmsPickSession.id == session_id)
        ).first()
        assert session is not None
        assert session.status == 'cancelled'

    def test_discarding_scans_says_what_was_dropped_in_the_audit_log(
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
            '20',
        )
        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        ).json()['id']
        scan = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 3},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text

        cancel = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/cancel',
            headers=doc_auth_headers,
        )
        assert cancel.status_code == status.HTTP_204_NO_CONTENT

        db_session.expire_all()
        entries = [
            entry.snapshot or {}
            for entry in db_session.scalars(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(doc_id))
            ).all()
            if (entry.snapshot or {}).get('wms_session_status') == 'cancelled'
        ]
        assert len(entries) == 1
        assert entries[0]['wms_session_id'] == session_id
        (dropped,) = entries[0]['wms_session_discarded']
        assert dropped.endswith(': 3')

    def test_discarding_nothing_names_nothing(
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
            '20',
        )
        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        ).json()['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/cancel',
            headers=doc_auth_headers,
        )

        db_session.expire_all()
        snapshots = [
            entry.snapshot or {}
            for entry in db_session.scalars(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(doc_id))
            ).all()
            if (entry.snapshot or {}).get('wms_session_status') == 'cancelled'
        ]
        assert len(snapshots) == 1
        assert 'wms_session_discarded' not in snapshots[0]


@pytest.mark.integration
class TestWmsFullFlow:
    def test_full_pick_then_document_complete(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/complete',
            headers=doc_auth_headers,
        )

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
        )
        assert complete.status_code == status.HTTP_200_OK
        assert complete.json()['status'] == 'COMPLETED'

        quant = _shelf_quant(
            db_session, doc_org.id, template_id, doc_source_location.id
        )
        assert float(quant.quantity) == 15.0

    def test_list_pick_sessions(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )

        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()['items']
        assert len(data) >= 1
        assert data[0]['document_id'] == doc_id


@pytest.mark.integration
class TestWmsGuards:
    """WMS integrity guards."""

    def _setup_out_with_stock(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        source_loc: StorageLocation,
        target_loc: StorageLocation,
        partner: Partner,
        item: Item,
        template: ProductTemplate,
        org: Organization,
        db: Session,
        engine: AsyncEngine,
    ) -> tuple[str, str, ShelfRow]:
        template_id = item.template_id or template.id
        _sow(db, engine, org, template, source_loc.id, '20')
        doc_id = _create_out_document(
            client,
            auth_headers,
            source_loc.id,
            target_loc.id,
            partner.id,
            template_id,
            item.id,
        )
        _confirm_document(client, auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start', headers=auth_headers
        )
        return (
            doc_id,
            start.json()['id'],
            _shelf_quant(db, org.id, template_id, source_loc.id),
        )

    def test_scan_rejected_on_completed_document(
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
        """Scan is rejected when document is no longer CONFIRMED."""
        doc_id, session_id, _ = self._setup_out_with_stock(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
            doc_org,
            db_session,
            async_engine_fixture,
        )
        # Directly set document to COMPLETED (bypass the guard — simulates race)
        from app.modules.warehouse.models import Document

        doc = db_session.scalar(
            select(Document).where(Document.id == uuid.UUID(doc_id))
        )
        assert doc is not None
        doc.status = 'COMPLETED'
        db_session.commit()
        # Scan — session is still active but document is COMPLETED
        pick_line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).first()
        assert pick_line is not None
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'rejected'

    def test_complete_blocked_by_active_wms_session(
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
        """``complete_document`` is blocked when WMS picking session is active."""
        doc_id, session_id, _ = self._setup_out_with_stock(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
            doc_org,
            db_session,
            async_engine_fixture,
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        detail = resp.json()['detail']
        assert detail['code'] == 'WMS_SESSION_ACTIVE'
        msg = detail['message']
        # The refusal names the kind of session standing in the way, and
        # carries nothing a worker cannot act on: the session's id is a
        # number the document page never showed and the API never needed
        # to speak.
        assert 'picking session' in msg.lower()
        assert _UUID_IN_TEXT.search(msg) is None, (
            f'message carries no raw session id; got: {msg!r}'
        )
        assert session_id not in msg

    def test_cancel_blocked_by_active_wms_session(
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
        """``cancel_document`` is blocked when WMS picking session is active."""
        doc_id, session_id, _ = self._setup_out_with_stock(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_item,
            doc_template,
            doc_org,
            db_session,
            async_engine_fixture,
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        detail = resp.json()['detail']
        assert detail['code'] == 'WMS_SESSION_ACTIVE'
        msg = detail['message']
        assert 'picking session' in msg.lower()
        assert _UUID_IN_TEXT.search(msg) is None, (
            f'message carries no raw session id; got: {msg!r}'
        )
        assert session_id not in msg


@pytest.mark.integration
class TestWmsPickLineCoverage:
    """A picking session covers the same lines a receiving session would.

    Lines reach a document by two roads: the product search sets
    ``product_template_id``, the scanner sets ``item_id``. A session that only
    understood the first one opened empty over documents built the second way.
    """

    def _create_out_document_item_only(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        source_location_id: uuid.UUID,
        target_location_id: uuid.UUID,
        partner_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> str:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(partner_id),
                'source_location_id': str(source_location_id),
                'target_location_id': str(target_location_id),
                'lines': [{'item_id': str(item_id), 'expected_quantity': 2}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        return cast(str, response.json()['id'])

    def test_start_pick_builds_line_from_item_without_template(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        doc_item.storage_location_id = doc_source_location.id
        db_session.commit()

        doc_id = self._create_out_document_item_only(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['total_lines'] == 1
        assert data['pending_lines'] == 1
        assert data['lines'][0]['product_name'] == doc_item.name

    def test_start_pick_resolves_the_group_from_item_template(
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
        record = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = self._create_out_document_item_only(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            record.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        session_id = resp.json()['id']

        pick_line = db_session.scalar(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        )
        assert pick_line is not None
        assert pick_line.anchor_id is not None, 'the line plans from a group'

    def test_complete_session_without_lines_is_rejected(
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
            '20',
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        # Strip the session down to what an unbuildable document used to produce.
        for line in db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).all():
            db_session.delete(line)
        db_session.commit()

        status_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}',
            headers=doc_auth_headers,
        )
        assert status_resp.status_code == status.HTTP_200_OK
        assert status_resp.json()['total_lines'] == 0

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/complete',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        detail = resp.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'no lines' in message.lower()

        session = db_session.scalar(
            select(WmsPickSession).where(WmsPickSession.id == uuid.UUID(session_id))
        )
        assert session is not None
        assert session.status == 'active'


@pytest.mark.integration
class TestPickLineCarriesTheGroup:
    """A line plans from a group and a lot: its shelf's anchor and a batch."""

    def test_line_names_the_group_and_the_lot(
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
        lot = StockLot(
            organization_id=doc_org.id,
            product_template_id=template_id,
            name='BATCH-GROUP-1',
        )
        db_session.add(lot)
        db_session.flush()
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
            lot_id=lot.id,
        )

        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED

        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(start.json()['id'])
            )
        ).one()
        assert line.anchor_id is not None, 'the line plans from a group'
        anchor = db_session.get(StockAnchor, line.anchor_id)
        assert anchor is not None
        assert anchor.product_template_id == template_id
        assert anchor.storage_location_id == doc_source_location.id
        assert line.lot_id == lot.id, 'the line plans from a batch'

    def test_the_line_plans_the_first_batch_on_the_shelf(
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
        """Same shelf, same product, two batches: the line plans the first."""
        template_id = doc_item.template_id or doc_template.id
        planned = StockLot(
            organization_id=doc_org.id,
            product_template_id=template_id,
            name='BATCH-PLANNED',
        )
        other = StockLot(
            organization_id=doc_org.id,
            product_template_id=template_id,
            name='BATCH-OTHER',
        )
        db_session.add_all([planned, other])
        db_session.flush()
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
            lot_id=planned.id,
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
            lot_id=other.id,
        )
        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).one()
        assert line.lot_id == planned.id, 'FIFO planned the first batch'
        assert line.lot_id != other.id


@pytest.mark.integration
class TestWmsPickSessionIsOwnedByItsOpener:
    """A session belongs to the picker who opened it.

    A colleague holding ``warehouse:write`` could work someone else's
    session through the raw API. The refusal is the same held-session
    envelope ``start`` already answers with, so the release dialog reads it
    unchanged; the release itself stays the release door's job.
    """

    def test_a_foreign_picker_is_refused_by_every_operation(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
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
            '20',
        )
        doc_id = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED
        session_id = start.json()['id']

        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).one()

        foreign = h.create_user(doc_org, email='picker-foreign@example.com')
        foreign_headers = h.get_auth_headers(foreign)

        operations: list[tuple[str, dict[str, Any]]] = [
            (
                'scan',
                {'json': {'barcode': doc_template.barcode, 'quantity': 1}},
            ),
            (
                'short-pick',
                {'json': {'line_id': str(line.id), 'picked_quantity': 1}},
            ),
            ('undo', {'params': {'line_id': str(line.id)}}),
            ('skip', {'params': {'line_id': str(line.id)}}),
            ('complete', {}),
            ('cancel', {}),
        ]
        for operation, kwargs in operations:
            resp = client.post(
                f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/{operation}',
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
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )
        assert own.status_code == status.HTTP_200_OK, own.text
        assert own.json()['status'] == 'picked'


@pytest.mark.integration
class TestWmsPickSessionUnderTheWrongDocument:
    """The document in the URL scopes the session id, for every door.

    The service found a session by id alone, so a session quoted under
    another document's URL was worked — on a document the URL never named.
    Both ids travel together; when they disagree the session is not there.
    """

    def test_every_operation_is_not_found_under_another_documents_url(
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
            '20',
        )
        doc_a = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        doc_b = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_a)
        _confirm_document(client, doc_auth_headers, doc_b)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_a}/picking/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED
        session_id = start.json()['id']

        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).one()

        operations: list[tuple[str, dict[str, Any]]] = [
            (
                'scan',
                {'json': {'barcode': doc_template.barcode, 'quantity': 1}},
            ),
            (
                'short-pick',
                {'json': {'line_id': str(line.id), 'picked_quantity': 1}},
            ),
            ('undo', {'params': {'line_id': str(line.id)}}),
            ('skip', {'params': {'line_id': str(line.id)}}),
            ('complete', {}),
            ('cancel', {}),
        ]
        for operation, kwargs in operations:
            resp = client.post(
                f'/api/v1/warehouse/documents/{doc_b}/picking/{session_id}/{operation}',
                headers=doc_auth_headers,
                **kwargs,
            )
            assert resp.status_code == status.HTTP_404_NOT_FOUND, (
                operation,
                resp.text,
            )
            assert resp.json()['detail']['code'] == 'PICKING_SESSION_NOT_FOUND', (
                operation
            )

        # The session is still the one doc_a opened, and still active.
        under_its_own = client.get(
            f'/api/v1/warehouse/documents/{doc_a}/picking/{session_id}',
            headers=doc_auth_headers,
        )
        assert under_its_own.status_code == status.HTTP_200_OK
        assert under_its_own.json()['status'] == 'active'

    def test_the_read_is_not_found_under_another_documents_url(
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
            '20',
        )
        doc_a = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        doc_b = _create_out_document(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm_document(client, doc_auth_headers, doc_a)
        _confirm_document(client, doc_auth_headers, doc_b)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_a}/picking/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED

        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_b}/picking/{start.json()["id"]}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()['detail']['code'] == 'PICKING_SESSION_NOT_FOUND'
