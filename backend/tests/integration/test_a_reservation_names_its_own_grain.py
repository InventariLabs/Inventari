"""A reservation row names its own grain: the group's anchor, the batch, the owner.

A row used to name only the quant it held stock on; the product, the shelf,
the batch and the owner were read off that quant, by the records' view and
by every lock that looked for a document's holds. The quants are gone and
the records are the only count, so the row carries its grain itself — the
grain of the records the stock was reserved from — and the view counts the
hold by it.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.stock_lot import StockLot
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.asyncio


class _Granary:
    def __init__(self) -> None:
        self.org: Organization
        self.keeper: UserContextDTO
        self.shelf_a: StorageLocation
        self.shelf_b: StorageLocation
        self.oats: ProductTemplate
        self.batch_1: StockLot
        self.batch_2: StockLot
        self.consignor: Partner


@pytest.fixture
async def granary(real_async_db_session: AsyncSession) -> _Granary:
    """Oats in three grains: two batches on shelf A, a consignor's on shelf B."""
    db = real_async_db_session
    fixture = _Granary()
    fixture.org = Organization(
        name=f'Granary {uuid4().hex[:6]}', enabled_modules=['core']
    )
    db.add(fixture.org)
    await db.flush()
    fixture.keeper = await shelf_keeper(db, fixture.org.id)
    storage_type = StorageType(
        name='Bin', type_code=f'BIN_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    fixture.shelf_a, fixture.shelf_b = (
        StorageLocation(
            name=name,
            organization_id=fixture.org.id,
            storage_type_id=storage_type.id,
            created_by=fixture.keeper.id,
        )
        for name in ('Bin A', 'Bin B')
    )
    fixture.oats = ProductTemplate(name='Oats', organization_id=fixture.org.id)
    fixture.consignor = Partner(
        organization_id=fixture.org.id, name='Consignor', type='SUPPLIER'
    )
    db.add_all([fixture.shelf_a, fixture.shelf_b, fixture.oats, fixture.consignor])
    await db.flush()
    fixture.batch_1, fixture.batch_2 = (
        StockLot(
            organization_id=fixture.org.id,
            product_template_id=fixture.oats.id,
            name=name,
        )
        for name in ('OAT-1', 'OAT-2')
    )
    db.add_all([fixture.batch_1, fixture.batch_2])
    await db.flush()

    keeper, oats = fixture.keeper, fixture.oats
    await put_on_shelf(
        db, keeper, oats, fixture.shelf_a.id, 4, lot_id=fixture.batch_1.id
    )
    await put_on_shelf(
        db, keeper, oats, fixture.shelf_a.id, 5, lot_id=fixture.batch_2.id
    )
    await put_on_shelf(
        db, keeper, oats, fixture.shelf_b.id, 6, owner_id=fixture.consignor.id
    )
    await db.commit()
    return fixture


async def _reserve(
    db: AsyncSession,
    granary: _Granary,
    quantity: str,
    location_id: UUID | None = None,
) -> UUID:
    document_id = uuid4()
    result = await core_api.stock.reserve_for_document_async(
        db,
        granary.org.id,
        granary.oats.id,
        location_id,
        Decimal(quantity),
        document_id=document_id,
    )
    assert result.success, result.message
    await db.commit()
    return document_id


async def test_every_row_carries_the_grain_it_reserved(
    real_async_db_session: AsyncSession, granary: _Granary
) -> None:
    db = real_async_db_session
    # Thirteen from every shelf: all three grains give some.
    document_id = await _reserve(db, granary, '13')

    rows = (
        await db.execute(
            select(StockReservation, StockAnchor)
            .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
            .where(StockReservation.document_id == document_id)
        )
    ).all()

    assert len(rows) == 3
    assert all(anchor.product_template_id == granary.oats.id for _, anchor in rows)
    assert {
        (anchor.storage_location_id, row.lot_id, row.owner_id) for row, anchor in rows
    } == {
        (granary.shelf_a.id, granary.batch_1.id, None),
        (granary.shelf_a.id, granary.batch_2.id, None),
        (granary.shelf_b.id, None, granary.consignor.id),
    }
    assert sum(row.quantity for row, _ in rows) == Decimal('13')


async def test_the_view_counts_each_hold_on_the_grain_its_row_names(
    real_async_db_session: AsyncSession, granary: _Granary
) -> None:
    """The view's promise per grain is the rows of that grain, and nothing else."""
    db = real_async_db_session
    await _reserve(db, granary, '13')
    await _reserve(db, granary, '1', granary.shelf_b.id)

    by_rows = {
        (shelf, lot, owner): held
        for shelf, lot, owner, held in (
            await db.execute(
                select(
                    StockAnchor.storage_location_id,
                    StockReservation.lot_id,
                    StockReservation.owner_id,
                    func.sum(StockReservation.quantity),
                )
                .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
                .where(StockAnchor.product_template_id == granary.oats.id)
                .group_by(
                    StockAnchor.storage_location_id,
                    StockReservation.lot_id,
                    StockReservation.owner_id,
                )
            )
        ).all()
    }
    view = stock_quants_from_records
    by_view = {
        (row.storage_location_id, row.lot_id, row.owner_id): row.reserved_quantity
        for row in (
            await db.execute(
                select(view).where(view.c.product_template_id == granary.oats.id)
            )
        ).all()
        if row.reserved_quantity
    }

    assert by_view == by_rows
    assert set(by_view) == {
        (granary.shelf_a.id, granary.batch_1.id, None),
        (granary.shelf_a.id, granary.batch_2.id, None),
        (granary.shelf_b.id, None, granary.consignor.id),
    }
