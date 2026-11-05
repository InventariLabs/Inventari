"""
Integration tests for StockMove records emitted from document execution.

Documents were once the only stock-mutating path that did NOT emit
StockMove rows, so the WMS movement ledger was missing every
document-driven receipt, dispatch, transfer and scrap. Now every stock
change a document makes writes its movement with
``reference_type='document'``, ``reference_id=doc.id``.

Tests:
- Receipt creates one StockMove (to_location, no from)
- Dispatch creates one StockMove (from_location, no to)
- Transfer creates one StockMove (both locations)
- FEFO dispatch creates one StockMove per consumed lot (per-lot breakdown)
- The /moves list endpoint exposes document moves alongside item moves
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import DocumentLine
from app.modules.warehouse.tests.integration._records import (
    shelf_quant,
    shelf_record,
    sow,
)

# The batches these tests order have to be batches the warehouse would still
# release: stock past its date is held back now, and fixed calendar dates
# quietly walked into the past — every one of these was in the future when
# it was typed. Relative dates keep the subject FEFO ordering rather than
# how long ago the file was written.
_TODAY = datetime.now(UTC).date()


def _in_months(months: int) -> date:
    return _TODAY + timedelta(days=30 * months)


def _create_in(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    target_location_id: UUID,
    template_id: UUID,
    quantity: int,
    batch_number: str | None = None,
) -> str:
    line: dict[str, object] = {
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if batch_number is not None:
        line['batch_number'] = batch_number

    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text
    return doc_id


def _create_out(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    source_location_id: UUID,
    target_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
    batch_number: str | None = None,
) -> str:
    line: dict[str, object] = {
        'item_id': str(item_id),
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if batch_number is not None:
        line['batch_number'] = batch_number

    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text
    return doc_id


def _create_int(
    client: TestClient,
    headers: dict[str, str],
    *,
    source_location_id: UUID,
    target_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'INT',
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
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text
    return doc_id


def _make_lot(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    name: str,
    use_by_date: date | None,
) -> StockLot:
    lot = StockLot(
        organization_id=org_id,
        product_template_id=template_id,
        name=name,
        use_by_date=use_by_date,
    )
    db_session.add(lot)
    db_session.flush()
    db_session.refresh(lot)
    return lot


def _put_batch(
    db_session: Session,
    engine: AsyncEngine,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    quantity: Decimal,
    lot_id: UUID | None = None,
) -> ShelfRow:
    """One record of the batch on the shelf; returns the group it makes there."""
    template = db_session.get(ProductTemplate, template_id)
    assert template is not None
    sow(
        db_session,
        engine,
        org_id,
        template,
        location_id,
        quantity,
        lot_id=lot_id,
    )
    return shelf_quant(db_session, org_id, template_id, location_id, lot_id=lot_id)


def _make_item(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    """The record the document line names: one already standing on the shelf.

    The stock itself went in through ``sow`` (per batch); this picks up one
    of those records, so the line names a real one instead of a scalar row
    no batch on the shelf stands behind.
    """
    return shelf_record(db_session, org_id, template_id, location_id)


def _ledger_on(db_session: Session, template_id: UUID, location_id: UUID) -> Decimal:
    """What the done movements of *template_id* net to on *location_id*."""
    total = Decimal('0')
    for move in db_session.scalars(
        select(StockMove).where(
            StockMove.product_template_id == template_id,
            StockMove.state == 'done',
        )
    ):
        if move.to_location_id == location_id:
            total += move.quantity
        if move.from_location_id == location_id:
            total -= move.quantity
    return total


def _doc_moves(
    db_session: Session,
    doc_id: UUID,
) -> list[StockMove]:
    return list(
        db_session.scalars(
            select(StockMove).where(
                StockMove.reference_type == 'document',
                StockMove.reference_id == doc_id,
            )
        ).all()
    )


def _rows_at(
    db_session: Session,
    template_id: UUID,
    location_id: UUID,
) -> list[Item]:
    """The records one product keeps on one shelf, oldest first."""
    return list(
        db_session.scalars(
            select(Item)
            .where(
                Item.template_id == template_id,
                Item.storage_location_id == location_id,
                Item.is_deleted.is_(False),
            )
            .order_by(Item.created_at.asc())
        ).all()
    )


def _run_doc(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, object],
) -> tuple[int, str, str]:
    """Create a document from *payload*, confirm and complete it.

    Returns the completion status, the document id and the completion body,
    so a test can assert on a refusal itself instead of tripping a helper's
    own assertion on the way there.
    """
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return complete.status_code, doc_id, complete.text


@pytest.mark.integration
class TestDocumentStockMoves:
    """Document execution must emit StockMove rows for the WMS ledger."""

    def test_receipt_creates_stock_move(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Move IN {uuid4().hex[:6]}')

        doc_id = _create_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=10,
            batch_number='LOT-IN',
        )

        moves = _doc_moves(db_session, UUID(doc_id))
        assert len(moves) == 1
        move = moves[0]
        assert move.to_location_id == doc_target_location.id
        assert move.from_location_id is None
        assert move.quantity == Decimal('10')
        assert move.reference_type == 'document'
        assert move.reference_id == UUID(doc_id)

    def test_dispatch_creates_stock_move(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Move OUT {uuid4().hex[:6]}')

        lot = _make_lot(db_session, doc_org.id, template.id, 'LOT-OUT', _in_months(3))
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
            lot_id=lot.id,
        )
        item = _make_item(
            db_session,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        db_session.commit()

        doc_id = _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=4,
            batch_number='LOT-OUT',
        )

        moves = _doc_moves(db_session, UUID(doc_id))
        assert len(moves) == 1
        move = moves[0]
        assert move.from_location_id == doc_source_location.id
        assert move.to_location_id is None
        assert move.quantity == Decimal('4')
        assert move.reference_type == 'document'
        assert move.reference_id == UUID(doc_id)

    def test_transfer_creates_stock_move_with_both_locations(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Move INT {uuid4().hex[:6]}')

        lot = _make_lot(db_session, doc_org.id, template.id, 'LOT-INT', _in_months(6))
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
            lot_id=lot.id,
        )
        item = _make_item(
            db_session,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        db_session.commit()

        doc_id = _create_int(
            client,
            doc_auth_headers,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=10,
        )

        moves = _doc_moves(db_session, UUID(doc_id))
        assert len(moves) == 1
        move = moves[0]
        assert move.from_location_id == doc_source_location.id
        assert move.to_location_id == doc_target_location.id
        assert move.quantity == Decimal('10')
        assert move.reference_type == 'document'
        assert move.reference_id == UUID(doc_id)

    def test_fefo_dispatch_creates_one_move_per_lot(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        """FEFO dispatch consumes across lots → one StockMove per consumed lot.

        An OUT without explicit batch/serial draws by the removal strategy,
        planned from the records, which returns a per-lot breakdown. The
        document executor must mirror that breakdown into StockMove rows so analytics
        (per-lot FIFO/FEFO, aging) see the lot structure.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'FEFO Move {uuid4().hex[:6]}')
        template.removal_strategy = 'FEFO'
        db_session.commit()
        db_session.refresh(template)

        lot_a = _make_lot(db_session, doc_org.id, template.id, 'LOT-A', _in_months(3))
        lot_b = _make_lot(db_session, doc_org.id, template.id, 'LOT-B', _in_months(12))
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('5'),
            lot_id=lot_a.id,
        )
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('5'),
            lot_id=lot_b.id,
        )
        item = _make_item(
            db_session,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        db_session.commit()

        # No batch_number → strategy decrement will pick LOT-A (earliest)
        # fully, then LOT-B for the remainder.
        doc_id = _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=7,
        )

        moves = _doc_moves(db_session, UUID(doc_id))
        assert len(moves) == 2, (
            f'Expected 2 StockMove rows (one per consumed lot), got {len(moves)}'
        )
        moves_by_lot = {m.lot_id: m for m in moves}
        assert lot_a.id in moves_by_lot
        assert lot_b.id in moves_by_lot
        assert moves_by_lot[lot_a.id].quantity == Decimal('5')
        assert moves_by_lot[lot_b.id].quantity == Decimal('2')
        for move in moves:
            assert move.from_location_id == doc_source_location.id
            assert move.to_location_id is None
            assert move.reference_type == 'document'

    def test_stock_moves_list_endpoint_returns_document_moves(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        """The /moves list endpoint must include document-emitted rows."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Endpoint Move {uuid4().hex[:6]}')

        # A batch on the shelf to move.
        lot = _make_lot(db_session, doc_org.id, template.id, 'LOT-EP', _in_months(9))
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
            lot_id=lot.id,
        )
        item = _make_item(
            db_session,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        db_session.commit()

        _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=3,
            batch_number='LOT-EP',
        )

        resp = client.get(
            '/api/v1/stock-moves',
            params={'product_template_id': str(template.id)},
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        moves = resp.json()['items']
        # At least one move with reference_type='document' must be returned.
        doc_moves = [m for m in moves if m['reference_type'] == 'document']
        assert len(doc_moves) >= 1
        assert all(
            m['from_location_id'] == str(doc_source_location.id) for m in doc_moves
        )


def _create_in_free_text(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    target_location_id: UUID,
    name: str,
    quantity: int,
    batch_number: str | None = None,
) -> str:
    """A receipt whose line is typed by hand: a name, no template."""
    line: dict[str, str | int] = {'name': name, 'expected_quantity': quantity}
    if batch_number is not None:
        line['batch_number'] = batch_number
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text
    return doc_id


@pytest.mark.integration
class TestOutboundOfACardlessRecord:
    """The doors beyond the receipt must not skip the ledger for a legacy row.

    Every executor used to gate its ledger writes on ``stock_template_id``:
    a record whose card was never minted (``items.template_id`` NULL — the
    shape of anything stocked before the catalogue existed) had its quantity
    taken off the record while the movement register, the shelf quant and
    the cost layers all read empty. The receipt already adopts the card such
    a row lacks; these tests hold the other doors to the same answer. Each
    runs a pair of documents differing in exactly one thing — whether the
    line's record carries a card — and demands the same number of movements
    from both.
    """

    def test_dispatch_of_a_cardless_record_adopts_a_card_and_moves(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Carded Out {uuid4().hex[:6]}')
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        carded = _make_item(
            db_session, doc_org.id, template.id, doc_source_location.id, Decimal('10')
        )
        legacy = Item(
            name=f'Legacy Out {uuid4().hex[:6]}',
            organization_id=doc_org.id,
            template_id=None,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('5'),
        )
        db_session.add(legacy)
        db_session.commit()

        common = {
            'type': 'OUT',
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
        }
        carded_status, carded_id, _ = _run_doc(
            client,
            doc_auth_headers,
            {
                **common,
                'lines': [
                    {
                        'item_id': str(carded.id),
                        'product_template_id': str(template.id),
                        'expected_quantity': 4,
                    }
                ],
            },
        )
        assert carded_status == status.HTTP_200_OK
        legacy_status, legacy_id, legacy_body = _run_doc(
            client,
            doc_auth_headers,
            {**common, 'lines': [{'item_id': str(legacy.id), 'expected_quantity': 2}]},
        )
        assert legacy_status == status.HTTP_200_OK, legacy_body

        carded_moves = _doc_moves(db_session, UUID(carded_id))
        legacy_moves = _doc_moves(db_session, UUID(legacy_id))
        assert len(carded_moves) == 1
        assert len(legacy_moves) == 1, (
            'a dispatch of a record without a card must record its movement '
            '— a silent skip is the bug'
        )

        db_session.expire_all()
        moved = db_session.get(Item, legacy.id)
        assert moved is not None, 'the record survived the dispatch'
        assert moved.template_id is not None, 'the dispatch bound a card'
        assert legacy_moves[0].product_template_id == moved.template_id
        assert legacy_moves[0].from_location_id == doc_source_location.id
        assert moved.quantity == Decimal('3'), 'the record lost what left it'

        line = db_session.scalar(
            select(DocumentLine).where(DocumentLine.document_id == UUID(legacy_id))
        )
        assert line is not None
        assert line.product_template_id == moved.template_id, (
            'the line closes with the card it moved under'
        )

        # The stock the record held predates the ledger, so adoption posts it
        # there before anything leaves: the shelf starts at five and the
        # dispatch takes its two off both sides, which is what the pair
        # (card, location) needs to keep saying one number.
        adopted = _ledger_on(db_session, moved.template_id, doc_source_location.id)
        assert adopted == moved.quantity == Decimal('3'), (
            f'the ledger nets the adopted card to {adopted} on its shelf'
        )

        carded_after = db_session.get(Item, carded.id)
        assert carded_after is not None
        assert carded_after.quantity == Decimal('6'), (
            'the carded control behaves as it always has'
        )

    def test_scrap_of_a_cardless_record_adopts_a_card_and_moves(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Carded Scrap {uuid4().hex[:6]}')
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        carded = _make_item(
            db_session, doc_org.id, template.id, doc_source_location.id, Decimal('10')
        )
        legacy = Item(
            name=f'Legacy Scrap {uuid4().hex[:6]}',
            organization_id=doc_org.id,
            template_id=None,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('5'),
        )
        db_session.add(legacy)
        db_session.commit()

        common = {
            'type': 'SCRAP',
            'reason_code': 'DAMAGED',
            'source_location_id': str(doc_source_location.id),
        }
        carded_status, carded_id, _ = _run_doc(
            client,
            doc_auth_headers,
            {
                **common,
                'lines': [
                    {
                        'item_id': str(carded.id),
                        'product_template_id': str(template.id),
                        'expected_quantity': 4,
                    }
                ],
            },
        )
        assert carded_status == status.HTTP_200_OK
        legacy_status, legacy_id, legacy_body = _run_doc(
            client,
            doc_auth_headers,
            {**common, 'lines': [{'item_id': str(legacy.id), 'expected_quantity': 2}]},
        )
        assert legacy_status == status.HTTP_200_OK, legacy_body

        carded_moves = _doc_moves(db_session, UUID(carded_id))
        legacy_moves = _doc_moves(db_session, UUID(legacy_id))
        assert len(carded_moves) == 1
        assert len(legacy_moves) == 1, (
            'a scrap of a record without a card must record its movement '
            '— a silent skip is the bug'
        )

        db_session.expire_all()
        scrapped = db_session.get(Item, legacy.id)
        assert scrapped is not None, 'the record survived the scrap'
        assert scrapped.template_id is not None, 'the scrap bound a card'
        assert legacy_moves[0].product_template_id == scrapped.template_id
        assert legacy_moves[0].from_location_id == doc_source_location.id
        assert scrapped.quantity == Decimal('3'), 'the record lost what left it'

        adopted = _ledger_on(db_session, scrapped.template_id, doc_source_location.id)
        assert adopted == scrapped.quantity == Decimal('3'), (
            'the write-off left the ledger and the record saying one number'
        )

    def test_transfer_of_a_cardless_record_moves_the_stock_whole(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Carded Int {uuid4().hex[:6]}')
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        carded = _make_item(
            db_session, doc_org.id, template.id, doc_source_location.id, Decimal('10')
        )
        legacy = Item(
            name=f'Legacy Int {uuid4().hex[:6]}',
            organization_id=doc_org.id,
            template_id=None,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('5'),
        )
        db_session.add(legacy)
        db_session.commit()

        common = {
            'type': 'INT',
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
        }
        carded_status, carded_id, _ = _run_doc(
            client,
            doc_auth_headers,
            {
                **common,
                'lines': [
                    {
                        'item_id': str(carded.id),
                        'product_template_id': str(template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        assert carded_status == status.HTTP_200_OK
        legacy_status, legacy_id, legacy_body = _run_doc(
            client,
            doc_auth_headers,
            {**common, 'lines': [{'item_id': str(legacy.id), 'expected_quantity': 5}]},
        )
        assert legacy_status == status.HTTP_200_OK, legacy_body

        carded_moves = _doc_moves(db_session, UUID(carded_id))
        legacy_moves = _doc_moves(db_session, UUID(legacy_id))
        assert len(carded_moves) == 1
        assert len(legacy_moves) == 1, (
            'a transfer of a record without a card must record its movement '
            '— a silent skip is the bug'
        )
        assert legacy_moves[0].from_location_id == doc_source_location.id
        assert legacy_moves[0].to_location_id == doc_target_location.id

        db_session.expire_all()
        moved = db_session.get(Item, legacy.id)
        assert moved is not None, 'the record survived the transfer'
        assert moved.template_id is not None, 'the transfer bound a card'
        assert moved.storage_location_id == doc_target_location.id
        assert moved.quantity == Decimal('5'), 'a transfer moves, it does not eat'

        # The pair (product, location) agrees on both sides of the move: the
        # record's five were posted on the shelf it stood on when the card was
        # adopted, and the move took them off that shelf and put them down on
        # the target, where the record stands now saying the same number.
        assert (
            moved.quantity
            == _ledger_on(db_session, moved.template_id, doc_target_location.id)
            == Decimal('5')
        )
        assert _ledger_on(
            db_session, moved.template_id, doc_source_location.id
        ) == Decimal('0'), (
            'the shelf the stock came off keeps nothing it no longer holds'
        )

        carded_after = db_session.get(Item, carded.id)
        assert carded_after is not None
        assert carded_after.storage_location_id == doc_target_location.id

    def test_outbound_refuses_a_card_kept_in_another_unit(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """A record kept in one unit does not silently join a card in another.

        The adoption goes through the same bind the receipt uses, and the
        bind takes the unit gate every door takes: the completion is refused
        by name, with both units in it, and nothing leaves the record.
        """

        from app.core.testing import ModuleTestHelper, error_message_pattern

        h = ModuleTestHelper(db_session)
        grams = h.get_uom('g')
        kilograms = h.get_uom('kg')
        name = f'Legacy Weight {uuid4().hex[:6]}'
        h.create_template(doc_org, name=name, uom_id=str(grams.id))
        legacy = Item(
            name=name,
            organization_id=doc_org.id,
            template_id=None,
            uom_id=kilograms.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('5'),
        )
        db_session.add(legacy)
        db_session.commit()

        complete_status, doc_id, body = _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(legacy.id), 'expected_quantity': 2}],
            },
        )
        assert complete_status == status.HTTP_400_BAD_REQUEST, body
        assert re.search(
            error_message_pattern(
                'item_unit_differs_from_template_confirmation_required',
                product=name,
                template_unit='g',
                chosen_unit='kg',
            ),
            body,
        ), 'the refusal names the record and both units'

        # The execution screen opens its confirmation dialog on this shape
        # and on nothing else: the code and the three fields, beside the
        # sentence API-only consumers have always read.
        detail = json.loads(body)['detail']
        assert detail['code'] == 'RECORD_UNIT_MISMATCH'
        assert detail['product'] == name
        assert detail['template_unit'] == 'g'
        assert detail['chosen_unit'] == 'kg'
        assert re.search(
            error_message_pattern(
                'item_unit_differs_from_template_confirmation_required',
                product=name,
                template_unit='g',
                chosen_unit='kg',
            ),
            detail['message'],
        ), "the structured envelope keeps the bind's own sentence"

        db_session.expire_all()
        item = db_session.get(Item, legacy.id)
        assert item is not None
        assert item.template_id is None, 'nothing was bound'
        assert item.quantity == Decimal('5'), 'nothing left the record'
        assert _doc_moves(db_session, UUID(doc_id)) == []
