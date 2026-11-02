"""A record carried to another shelf takes its own stock, and asks the rows what is held.

Carrying a record read the quant table twice. Whether the shelf it left held
reservations was read off the quants' running total, which was only the
mirror of the reservation rows; and the goods it took off were the quant's,
by whichever path the quants allowed. The records are the count, and the
table is gone: the refusal reads the rows through the records' view, and the
movement is posted for the record's own grain — its shelf, its batch, its
owner — so the batch the record carries is the batch the register moves, on
both sides.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemMove
from app.services.items import move_item

from ._core_api_helpers import make_template, make_user_context
from ._shelf import put_on_shelf, reserve_for_an_order

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _other_shelf(db: AsyncSession, org_id, user_id) -> StorageLocation:
    shelf = StorageLocation(organization_id=org_id, name='Shelf B', created_by=user_id)
    db.add(shelf)
    await db.flush()
    return shelf


async def _by_batch(db: AsyncSession, source, template_id) -> dict:
    """``{(shelf, batch): quantity}`` of *source*, the records' view."""
    rows = await db.execute(
        select(
            source.c.storage_location_id,
            source.c.lot_id,
            func.sum(source.c.quantity),
        )
        .where(source.c.product_template_id == template_id)
        .group_by(source.c.storage_location_id, source.c.lot_id)
    )
    return {(shelf, lot): qty for shelf, lot, qty in rows.all() if qty}


async def test_the_refusal_reads_the_reservation_rows(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    shelf_a = async_test_storage_location.id
    shelf_b = await _other_shelf(db, org_id, async_test_user.id)
    template = await db.run_sync(lambda s: make_template(s, org_id, name='Rice'))
    record = await put_on_shelf(db, async_test_user, template, shelf_a, 6)
    await put_on_shelf(db, async_test_user, template, shelf_a, 4)
    # The order's rows are the hold; nothing else says so.
    await reserve_for_an_order(db, template, shelf_a, 4)
    await db.commit()

    with pytest.raises(ValueError, match='reservation'):
        await move_item(
            db,
            record,
            ItemMove(to_location_id=shelf_b.id),
            user=make_user_context(org_id, async_test_user.id),
        )


async def test_a_record_without_a_batch_carries_its_own_grain(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    shelf_a = async_test_storage_location.id
    shelf_b = await _other_shelf(db, org_id, async_test_user.id)
    template = await db.run_sync(lambda s: make_template(s, org_id, name='Lentils'))
    lot = StockLot(
        organization_id=org_id,
        product_template_id=template.id,
        name=f'LOT-{uuid.uuid4().hex[:6]}',
    )
    db.add(lot)
    await db.flush()
    # The batch arrives first, so the product's strategy (first in, first
    # out) would hand it over before the stock with no batch.
    await put_on_shelf(db, async_test_user, template, shelf_a, 5, lot_id=lot.id)
    await db.commit()
    record = await put_on_shelf(db, async_test_user, template, shelf_a, 3)
    await db.commit()

    await move_item(
        db,
        record,
        ItemMove(to_location_id=shelf_b.id),
        user=make_user_context(org_id, async_test_user.id),
    )
    await db.commit()

    expected = {(shelf_a, lot.id): Decimal('5'), (shelf_b.id, None): Decimal('3')}
    assert await _by_batch(db, stock_quants_from_records, template.id) == expected
    moved = (
        await db.execute(
            select(StockMove.lot_id, StockMove.quantity).where(
                StockMove.product_template_id == template.id,
                StockMove.from_location_id == shelf_a,
                StockMove.to_location_id == shelf_b.id,
            )
        )
    ).all()
    assert moved == [(None, Decimal('3'))]
