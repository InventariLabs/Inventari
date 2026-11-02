"""The document executor keeps each record on the batch its stock is in.

A record names its batch and owner (``Item.lot_id``, ``Item.owner_id``), and
the executor used to write records and quants separately — with the
record's own posting off — so every door had to keep the two on the same
batch itself. None did:

- a receipt with a batch opened, or topped up, a record that named none,
  while the quant took the batch — two batches on one shelf became one
  record;
- a dispatch took the records down itself, the one the line named first and
  then by expiry, while the quants went by the removal strategy, so a line
  naming the later batch's record took that record down and the earlier
  batch's quant;
- a transfer that named no batch moved the quants by strategy while the
  record carried its own batch, and a partial line left the remainder as a
  record without one;
- a correction naming no batch changed the batch-less quant under a record
  that has one.

The quants are gone; the records are the stock, and the ledger's movements
say which batch each change was made on. Every scenario below is built so the
records and the movements agree batch by batch before the document runs;
whatever is out of step afterwards is the door's own doing.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import (
    shelf_quant,
    sow,
)

pytestmark = pytest.mark.integration


def _run(
    client: TestClient, headers: dict[str, str], payload: dict[str, Any]
) -> dict[str, Any]:
    created = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    completed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    return dict(completed.json())


class _Stock:
    """One product's stock: its records and the movements that put them there."""

    def __init__(
        self, db: Session, engine: AsyncEngine, template: ProductTemplate
    ) -> None:
        self.db = db
        self.engine = engine
        self.template = template

    def batch(self, name: str, *, expires: date | None = None) -> StockLot:
        lot = StockLot(
            organization_id=self.template.organization_id,
            product_template_id=self.template.id,
            name=name,
            expiry_date=expires,
        )
        self.db.add(lot)
        self.db.flush()
        return lot

    def on(
        self,
        shelf: StorageLocation,
        qty: str,
        *,
        lot: StockLot,
        age: int,
    ) -> Item:
        """A record of the batch; ``age`` in days ages the record, oldest first for FIFO."""
        return sow(
            self.db,
            self.engine,
            self.template.organization_id,
            self.template,
            shelf.id,
            Decimal(qty),
            lot_id=lot.id,
            backdate_days=age,
        )

    def records(self) -> dict[tuple[UUID, UUID | None], Decimal]:
        """What the records hold, per (shelf, batch)."""
        self.db.expire_all()
        rows = self.db.execute(
            select(Item.storage_location_id, Item.lot_id, Item.quantity).where(
                Item.template_id == self.template.id,
                Item.is_deleted.is_(False),
            )
        ).all()
        held: dict[tuple[UUID, UUID | None], Decimal] = {}
        for shelf, lot, qty in rows:
            held[(shelf, lot)] = held.get((shelf, lot), Decimal('0')) + qty
        return {grain: qty for grain, qty in held.items() if qty}

    def moved(self) -> dict[tuple[UUID, UUID | None], Decimal]:
        """What the done movements net to, per (shelf, batch)."""
        self.db.expire_all()
        rows = self.db.execute(
            select(
                StockMove.to_location_id,
                StockMove.from_location_id,
                StockMove.lot_id,
                StockMove.quantity,
            ).where(
                StockMove.product_template_id == self.template.id,
                StockMove.state == 'done',
            )
        ).all()
        netted: dict[tuple[UUID, UUID | None], Decimal] = {}
        for to_shelf, from_shelf, lot, qty in rows:
            if to_shelf is not None:
                netted[(to_shelf, lot)] = (
                    netted.get((to_shelf, lot), Decimal('0')) + qty
                )
            if from_shelf is not None:
                netted[(from_shelf, lot)] = (
                    netted.get((from_shelf, lot), Decimal('0')) - qty
                )
        return {grain: qty for grain, qty in netted.items() if qty}

    def quantity_of(self, record: Item) -> Decimal:
        self.db.expire_all()
        return self.db.execute(
            select(Item.quantity).where(Item.id == record.id)
        ).scalar_one()


@pytest.fixture
def stock(
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_template: ProductTemplate,
) -> _Stock:
    return _Stock(db_session, async_engine_fixture, doc_template)


def test_a_receipt_of_two_batches_on_one_shelf_opens_two_records(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_template: ProductTemplate,
    stock: _Stock,
) -> None:
    _run(
        client,
        doc_auth_headers,
        {
            'type': 'IN',
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'product_template_id': str(doc_template.id),
                    'expected_quantity': 4,
                    'batch_number': 'LOT-ONE',
                },
                {
                    'product_template_id': str(doc_template.id),
                    'expected_quantity': 6,
                    'batch_number': 'LOT-TWO',
                },
            ],
        },
    )

    assert stock.records() == stock.moved()
    assert len(stock.records()) == 2
    assert None not in {lot for _, lot in stock.records()}


def test_a_dispatch_takes_the_records_of_the_batch_the_shelf_gave_up(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    stock: _Stock,
) -> None:
    today = date.today()
    earlier = stock.on(
        doc_source_location,
        '10',
        lot=stock.batch('LOT-EARLY', expires=today + timedelta(days=10)),
        age=2,
    )
    later = stock.on(
        doc_source_location,
        '10',
        lot=stock.batch('LOT-LATE', expires=today + timedelta(days=90)),
        age=1,
    )
    db_session.commit()

    # The line names the later batch's record; the shelf hands out the
    # earlier batch first.
    _run(
        client,
        doc_auth_headers,
        {
            'type': 'OUT',
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'lines': [{'item_id': str(later.id), 'expected_quantity': 4}],
        },
    )

    assert (stock.quantity_of(earlier), stock.quantity_of(later)) == (
        Decimal('6'),
        Decimal('10'),
    )
    assert stock.records() == stock.moved()


def test_a_scrap_takes_the_records_of_the_batch_the_shelf_gave_up(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    db_session: Session,
    stock: _Stock,
) -> None:
    earlier = stock.on(doc_source_location, '10', lot=stock.batch('LOT-A'), age=2)
    later = stock.on(doc_source_location, '10', lot=stock.batch('LOT-B'), age=1)
    db_session.commit()

    _run(
        client,
        doc_auth_headers,
        {
            'type': 'SCRAP',
            'reason_code': 'DAMAGED',
            'source_location_id': str(doc_source_location.id),
            'lines': [{'item_id': str(later.id), 'expected_quantity': 3}],
        },
    )

    assert (stock.quantity_of(earlier), stock.quantity_of(later)) == (
        Decimal('7'),
        Decimal('10'),
    )
    assert stock.records() == stock.moved()


def test_a_transfer_that_names_no_batch_carries_the_records_own(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    db_session: Session,
    stock: _Stock,
) -> None:
    stock.on(doc_source_location, '5', lot=stock.batch('LOT-OLD'), age=2)
    moved = stock.on(doc_source_location, '5', lot=stock.batch('LOT-NEW'), age=1)
    db_session.commit()

    _run(
        client,
        doc_auth_headers,
        {
            'type': 'INT',
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [{'item_id': str(moved.id), 'expected_quantity': 5}],
        },
    )

    assert stock.records() == stock.moved()
    assert (doc_target_location.id, moved.lot_id) in stock.moved()


def test_a_partial_transfer_leaves_the_remainder_on_the_same_batch(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    db_session: Session,
    stock: _Stock,
) -> None:
    lot = stock.batch('LOT-SPLIT')
    record = stock.on(doc_source_location, '10', lot=lot, age=1)
    db_session.commit()

    _run(
        client,
        doc_auth_headers,
        {
            'type': 'INT',
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [{'item_id': str(record.id), 'expected_quantity': 4}],
        },
    )

    assert stock.records() == {
        (doc_source_location.id, lot.id): Decimal('6'),
        (doc_target_location.id, lot.id): Decimal('4'),
    }
    assert stock.records() == stock.moved()


def test_a_transfer_of_a_consigned_batch_stays_the_consignors(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    stock: _Stock,
) -> None:
    """A record whose stock is a consignor's moves under that name: the
    group that lands on the target shelf is the consignor's, and the record
    itself keeps naming them — the transfer carries ``owner_id`` at both
    ends, and a consignor's goods do not become the house's on the way."""
    lot = stock.batch('LOT-CONSIGNED')
    organization_id = stock.template.organization_id
    assert organization_id is not None
    record = sow(
        db_session,
        async_engine_fixture,
        organization_id,
        stock.template,
        doc_source_location.id,
        Decimal('5'),
        lot_id=lot.id,
        owner_id=doc_partner.id,
    )
    db_session.commit()

    _run(
        client,
        doc_auth_headers,
        {
            'type': 'INT',
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [{'item_id': str(record.id), 'expected_quantity': 5}],
        },
    )

    db_session.expire_all()
    moved = db_session.get(Item, record.id)
    assert moved is not None
    assert moved.owner_id == doc_partner.id
    assert moved.storage_location_id == doc_target_location.id
    landed = shelf_quant(
        db_session,
        organization_id,
        stock.template.id,
        doc_target_location.id,
        lot_id=lot.id,
    )
    assert landed.owner_id == doc_partner.id
    assert stock.records() == stock.moved()


def test_an_adjustment_that_names_no_batch_changes_the_records_own(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    db_session: Session,
    stock: _Stock,
) -> None:
    lot = stock.batch('LOT-ADJUSTED')
    record = stock.on(doc_source_location, '5', lot=lot, age=1)
    db_session.commit()

    _run(
        client,
        doc_auth_headers,
        {
            'type': 'ADJUSTMENT',
            'target_location_id': str(doc_source_location.id),
            'lines': [{'item_id': str(record.id), 'expected_quantity': 3}],
        },
    )

    assert stock.records() == {(doc_source_location.id, lot.id): Decimal('8')}
    assert stock.records() == stock.moved()


def test_a_correction_changes_the_records_of_the_batch_it_corrects(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_template: ProductTemplate,
    stock: _Stock,
) -> None:
    original = _run(
        client,
        doc_auth_headers,
        {
            'type': 'IN',
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'product_template_id': str(doc_template.id),
                    'expected_quantity': 10,
                    'batch_number': 'LOT-CORRECTED',
                }
            ],
        },
    )
    correction = client.post(
        '/api/v1/warehouse/corrections',
        headers=doc_auth_headers,
        json={
            'corrects_document_id': original['id'],
            'reason_code': 'DATA_ENTRY_ERROR',
            'lines': [
                {
                    'original_line_number': original['lines'][0]['line_number'],
                    'quantity_delta': -2,
                }
            ],
        },
    )
    assert correction.status_code == status.HTTP_201_CREATED, correction.text
    correction_id = correction.json()['id']
    for step in ('confirm', 'complete'):
        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/{step}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    (grain,) = stock.records()
    assert grain[1] is not None
    assert stock.records() == stock.moved() == {grain: Decimal('8')}


def test_a_correction_naming_no_batch_changes_the_records_own(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    stock: _Stock,
) -> None:
    """A dispatch named no batch, so neither does its correction's line."""
    lot = stock.batch('LOT-DISPATCHED')
    record = stock.on(doc_source_location, '10', lot=lot, age=1)
    db_session.commit()
    original = _run(
        client,
        doc_auth_headers,
        {
            'type': 'OUT',
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'lines': [{'item_id': str(record.id), 'expected_quantity': 3}],
        },
    )

    # One unit fewer left than the dispatch said: it comes back.
    correction = client.post(
        '/api/v1/warehouse/corrections',
        headers=doc_auth_headers,
        json={
            'corrects_document_id': original['id'],
            'reason_code': 'DATA_ENTRY_ERROR',
            'lines': [
                {
                    'original_line_number': original['lines'][0]['line_number'],
                    'quantity_delta': -1,
                }
            ],
        },
    )
    assert correction.status_code == status.HTTP_201_CREATED, correction.text
    correction_id = correction.json()['id']
    for step in ('confirm', 'complete'):
        resp = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/{step}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    assert (
        stock.records()
        == stock.moved()
        == {(doc_source_location.id, lot.id): Decimal('8')}
    )
