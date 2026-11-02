"""A dispatch or a scrap leaves the register one movement per batch it took.

The draw (``take_from_the_records_async``) writes the records, the quants
and the movements in one call; the door writes no movement of its own. A
door that wrote them again from the draw's answer would put every batch in
the register twice — which is what the count here is for.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import sow


class _Shelf:
    """Batch A (earlier date) in two records, three and four; batch B in one of five."""

    def __init__(
        self, db: Session, engine: AsyncEngine, org: Organization, shelf_id: UUID
    ):
        self.db = db
        h = ModuleTestHelper(db)
        self.template = h.create_template(org, name=f'One Move {uuid4().hex[:6]}')
        self.template.removal_strategy = 'FEFO'
        db.commit()
        today = datetime.now(UTC).date()
        self.lot_a, self.lot_b = (
            self._lot(org.id, name, today + timedelta(days=days))
            for name, days in (('LOT-A', 90), ('LOT-B', 270))
        )
        self.records = [
            sow(db, engine, org, self.template, shelf_id, Decimal(qty), lot_id=lot.id)
            for qty, lot in (('3', self.lot_a), ('4', self.lot_a), ('5', self.lot_b))
        ]

    def _lot(self, org_id: UUID, name: str, use_by: date) -> StockLot:
        lot = StockLot(
            organization_id=org_id,
            product_template_id=self.template.id,
            name=name,
            use_by_date=use_by,
        )
        self.db.add(lot)
        self.db.flush()
        return lot

    def moves(self, doc_id: str) -> list[tuple[UUID | None, Decimal]]:
        """Every movement of the product off the shelf since it was stocked, each naming *doc_id*.

        Read by product, not by document: a second writer that named no
        document would still put the batch in the register twice.
        """
        self.db.expire_all()
        moves = list(
            self.db.scalars(
                select(StockMove).where(
                    StockMove.product_template_id == self.template.id,
                    StockMove.from_location_id.is_not(None),
                )
            )
        )
        assert {move.reference_id for move in moves} == {UUID(doc_id)}
        return sorted((move.lot_id, move.quantity) for move in moves)

    def given_up(self, before: list[Decimal]) -> dict[UUID | None, Decimal]:
        """What the records lost since *before*, batch by batch."""
        self.db.expire_all()
        lost: dict[UUID | None, Decimal] = {}
        for record, held in zip(self.records, before, strict=True):
            now = cast(Item, self.db.get(Item, record.id)).quantity or Decimal('0')
            if held != now:
                lost[record.lot_id] = lost.get(record.lot_id, Decimal('0')) + held - now
        return lost

    def held(self) -> list[Decimal]:
        self.db.expire_all()
        return [
            cast(Item, self.db.get(Item, r.id)).quantity or Decimal('0')
            for r in self.records
        ]


def _run(client: TestClient, headers: dict[str, str], body: dict[str, object]) -> str:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    for step in ('confirm', 'complete'):
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/{step}',
            headers=headers,
            json={'complete_as_planned': True} if step == 'complete' else None,
        )
        assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


def test_a_dispatch_writes_one_move_per_batch_it_took(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
) -> None:
    """Nine out: all of A (two records) and two of B — two movements, not three or four."""
    shelf = _Shelf(db_session, async_engine_fixture, doc_org, doc_source_location.id)
    before = shelf.held()

    doc_id = _run(
        client,
        doc_auth_headers,
        {
            'type': 'OUT',
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'item_id': str(shelf.records[0].id),
                    'product_template_id': str(shelf.template.id),
                    'expected_quantity': 9,
                }
            ],
        },
    )

    assert shelf.given_up(before) == {
        shelf.lot_a.id: Decimal('7'),
        shelf.lot_b.id: Decimal('2'),
    }
    assert shelf.moves(doc_id) == sorted(
        [(shelf.lot_a.id, Decimal('7')), (shelf.lot_b.id, Decimal('2'))]
    )


def test_a_scrap_of_a_named_batch_writes_one_move_for_it(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
) -> None:
    """Five of A scrapped by name, off both its records: one movement of five."""
    shelf = _Shelf(db_session, async_engine_fixture, doc_org, doc_source_location.id)
    before = shelf.held()

    doc_id = _run(
        client,
        doc_auth_headers,
        {
            'type': 'SCRAP',
            'reason_code': 'DAMAGED',
            'source_location_id': str(doc_source_location.id),
            'lines': [
                {
                    'item_id': str(shelf.records[1].id),
                    'product_template_id': str(shelf.template.id),
                    'expected_quantity': 5,
                    'batch_number': 'LOT-A',
                }
            ],
        },
    )

    assert shelf.given_up(before) == {shelf.lot_a.id: Decimal('5')}
    assert shelf.moves(doc_id) == [(shelf.lot_a.id, Decimal('5'))]
