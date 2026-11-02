"""A draw on every shelf hands stock out in the removal order.

A production run asks for an ingredient, not for an ingredient on a
particular shelf. The maker module used to answer that with a re-implementation
of Core's FEFO/FIFO sort, in Python over DTOs, carrying a comment naming the
line numbers it mirrored — a synchronisation kept by hand.

The rule is now written once, as the draw plan over the records, and this
checks that a draw with no shelf named (``take_from_the_records_async`` with
``storage_location_id=None``, the production run's draw) obeys it: earliest
date first under FEFO, oldest record first under FIFO, and nothing taken at
all when the whole request cannot be met. The stock stands in records put on
the shelves the way the application puts it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services._stock_quant_ops import take_from_the_records_async
from tests.integration._shelf import put_on_shelf, reserve_for_an_order, shelf_keeper

pytestmark = pytest.mark.integration


async def _shelf(
    db: AsyncSession, org_id, name: str, storage_type: StorageType, user_id
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        storage_type_id=storage_type.id,
    )
    db.add(location)
    await db.flush()
    return location


async def _stock(
    db: AsyncSession,
    org_id,
    template: ProductTemplate,
    location: StorageLocation,
    quantity: str,
    *,
    created_at: datetime,
    use_by: date | None = None,
) -> Item:
    """A record of *quantity* on the shelf, as old as *created_at*; returns the record."""
    lot_id = None
    if use_by is not None:
        lot = StockLot(
            organization_id=org_id,
            product_template_id=template.id,
            name=f'LOT-{uuid.uuid4().hex[:6]}',
            use_by_date=use_by,
        )
        db.add(lot)
        await db.flush()
        lot_id = lot.id
    keeper = await shelf_keeper(db, org_id)
    record = await put_on_shelf(
        db, keeper, template, location.id, quantity, lot_id=lot_id
    )
    await db.execute(
        update(Item).where(Item.id == record.id).values(created_at=created_at)
    )
    return record


async def _on_shelf(db: AsyncSession, record: Item) -> Decimal:
    """What the record's group holds now; a group with no stock left has no row."""
    row = await db.scalar(
        select(ShelfRow).where(
            ShelfRow.product_template_id == record.template_id,
            ShelfRow.storage_location_id == record.storage_location_id,
            ShelfRow.lot_id.is_not_distinct_from(record.lot_id),
        )
    )
    return row.quantity if row is not None else Decimal('0')


async def _take(db: AsyncSession, org_id, template: ProductTemplate, quantity: str):
    """The production run's draw: every shelf of the product, in its removal order."""
    return await take_from_the_records_async(
        db, org_id, template.id, None, Decimal(quantity)
    )


async def _template(db: AsyncSession, org_id, strategy: str | None) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name=f'Mąka {uuid.uuid4().hex[:6]}',
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        removal_strategy=strategy,
    )
    db.add(template)
    await db.flush()
    return template


@pytest.mark.asyncio
class TestStockIsTakenFromEveryShelfInOrder:
    async def test_fefo_takes_the_shelf_with_the_earlier_date(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_type: StorageType,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        storage_type = async_test_storage_type
        template = await _template(db, org_id, 'FEFO')
        old_stock = await _shelf(
            db, org_id, 'Magazyn A', storage_type, async_test_user.id
        )
        new_stock = await _shelf(
            db, org_id, 'Magazyn B', storage_type, async_test_user.id
        )
        today = date.today()
        now = datetime.now()

        # The later date sits on the shelf that was filled first, so FIFO
        # and FEFO would answer differently — which is the point.
        fresh = await _stock(
            db,
            org_id,
            template,
            old_stock,
            '5',
            created_at=now - timedelta(days=10),
            use_by=today + timedelta(days=90),
        )
        expiring = await _stock(
            db,
            org_id,
            template,
            new_stock,
            '5',
            created_at=now,
            use_by=today + timedelta(days=2),
        )

        taken = await _take(db, org_id, template, '3')

        assert [(t.storage_location_id, t.lot_id) for t in taken] == [
            (new_stock.id, expiring.lot_id)
        ]
        assert await _on_shelf(db, expiring) == Decimal('2')
        assert await _on_shelf(db, fresh) == Decimal('5')

    async def test_fifo_takes_the_shelf_that_was_filled_first(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_type: StorageType,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        storage_type = async_test_storage_type
        template = await _template(db, org_id, 'FIFO')
        first = await _shelf(db, org_id, 'Magazyn A', storage_type, async_test_user.id)
        second = await _shelf(db, org_id, 'Magazyn B', storage_type, async_test_user.id)
        now = datetime.now()

        older = await _stock(
            db, org_id, template, first, '2', created_at=now - timedelta(days=10)
        )
        newer = await _stock(db, org_id, template, second, '5', created_at=now)

        taken = await _take(db, org_id, template, '4')

        assert [t.storage_location_id for t in taken] == [first.id, second.id]
        assert [t.consumed for t in taken] == [Decimal('2'), Decimal('2')]
        assert await _on_shelf(db, older) == Decimal('0'), (
            'the first shelf gave up all it had: its group is gone'
        )
        assert await _on_shelf(db, newer) == Decimal('3')

    async def test_a_deficit_takes_nothing_at_all(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_type: StorageType,
        async_test_user,
    ) -> None:
        """A run that fails on its fourth ingredient must not have eaten
        the first three."""
        db = real_async_db_session
        org_id = async_test_household.id
        storage_type = async_test_storage_type
        template = await _template(db, org_id, 'FIFO')
        shelf = await _shelf(db, org_id, 'Magazyn A', storage_type, async_test_user.id)
        record = await _stock(
            db, org_id, template, shelf, '2', created_at=datetime.now()
        )

        with pytest.raises(ValueError, match='Insufficient stock for template'):
            await _take(db, org_id, template, '5')

        assert await _on_shelf(db, record) == Decimal('2')

    async def test_reserved_stock_is_not_offered(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_type: StorageType,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        storage_type = async_test_storage_type
        template = await _template(db, org_id, 'FIFO')
        shelf = await _shelf(db, org_id, 'Magazyn A', storage_type, async_test_user.id)
        await _stock(db, org_id, template, shelf, '10', created_at=datetime.now())
        await reserve_for_an_order(db, template, shelf.id, 8)

        with pytest.raises(ValueError, match='available 2'):
            await _take(db, org_id, template, '3')
