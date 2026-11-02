"""Two moves of one record carry the same holding off one shelf twice.

``PUT /items/{id}`` with a shelf and no quantity is a read-modify-write even
though no number is typed: ``update_item`` carries what the caller fetched —
``old_location_id`` and ``old_quantity`` — from the old shelf to the new one
through ``carry_record_stock_async``. A quantity edit took the record's stock
lock and read the grain again under it; a shelf-only edit took the shelf
groups and not that lock, so two moves that had both fetched the record from
shelf A each carried the same 10 units off it. One record moved A→B in one
request and A→C in the other posted A:-10,B:+10 and A:-10,C:+10 while the
record could stand on only one of the two shelves: the per-shelf
shelf-versus-ledger pair drifted on the shelf it left and on the one it
never reached.

The door itself must hold the lock — the route reads
``item_in.quantity is not None`` to pick its locking fetch, so a shelf-only
edit arrives unlocked, and ``core_api.items.update_async`` and a re-imported sheet
fetch without a lock at all. Here both sessions load the record, meet, and
only then edit: the interleaving the door has to survive on its own, the
same shape ``test_two_edits_of_one_quantity`` uses next door.

The batch door, ``bulk_update_items``, snapshots each record the same way
and carried the same holding off the same shelf twice. Its probe lives here
beside the single edit's: the two doors write the same bridge and must
answer for it the same way.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemBulkUpdate, ItemUpdate
from app.services.items import bulk_update_items, update_item
from tests.integration._core_api_helpers import make_template, make_user_context
from tests.integration._shelf import put_on_shelf


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


async def _net_moved(
    db: AsyncSession, org_id: UUID, template_id: UUID, location_id: UUID
) -> Decimal:
    """What the ledger moved onto *location_id*, arrivals less departures."""
    totals: list[Decimal] = []
    for column in (StockMove.to_location_id, StockMove.from_location_id):
        total = await db.scalar(
            select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
                StockMove.organization_id == org_id,
                StockMove.product_template_id == template_id,
                column == location_id,
                StockMove.state == 'done',
            )
        )
        totals.append(total or Decimal('0'))
    arrived, left = totals
    return arrived - left


async def _held(db: AsyncSession, template_id: UUID, location_id: UUID) -> Decimal:
    """What the live records on *location_id* hold."""
    held = await db.scalar(
        select(func.coalesce(func.sum(Item.quantity), 0)).where(
            Item.template_id == template_id,
            Item.storage_location_id == location_id,
            Item.is_deleted.is_(False),
        )
    )
    return held or Decimal('0')


@pytest.mark.integration
@pytest.mark.asyncio
class TestTwoShelfMoves:
    async def _two_moves_at_once(
        self,
        db: AsyncSession,
        org_id: UUID,
        user,
        source: StorageLocation,
    ) -> tuple[UUID, ProductTemplate, list[StorageLocation]]:
        """Two sessions that fetched the record from one shelf, then move it apart.

        Both reads happen before either edit locks anything, which is the
        interleaving a route-level gather cannot promise: the second edit
        still holds the shelf and the number its fetch saw.
        """
        template = await db.run_sync(lambda s: make_template(s, org_id, name='Basil'))
        item = await put_on_shelf(db, user, template, source.id, 10)
        item_id = item.id
        targets = [
            StorageLocation(
                organization_id=org_id,
                name=f'QA shelf {index} {uuid4().hex[:6]}',
                created_by=user.id,
            )
            for index in range(2)
        ]
        db.add_all(targets)
        await db.commit()

        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        read_by = [asyncio.Event(), asyncio.Event()]

        async def edit(slot: int, to_location_id: UUID) -> None:
            async with factory() as session:
                record = await session.get(Item, item_id)
                assert record is not None
                read_by[slot].set()
                await asyncio.wait_for(read_by[1 - slot].wait(), timeout=5)
                await update_item(
                    session,
                    record,
                    ItemUpdate(location_id=to_location_id),
                    make_user_context(org_id, user.id),
                )
                await session.commit()

        try:
            await asyncio.gather(edit(0, targets[0].id), edit(1, targets[1].id))
        finally:
            await engine.dispose()
        return item_id, template, targets

    async def test_each_shelf_still_equals_what_the_ledger_moved(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        db = real_async_db_session
        org_id = async_test_household.id
        source = async_test_storage_location
        item_id, template, targets = await self._two_moves_at_once(
            db, org_id, async_test_user, source
        )

        await db.rollback()
        for location in (source, *targets):
            held = await _held(db, template.id, location.id)
            moved = await _net_moved(db, org_id, template.id, location.id)
            assert held == moved, (
                f'{location.name}: the shelf holds {held} but the ledger moved '
                f'{moved} — the two moves carried the same holding off one shelf'
            )
        final = await db.scalar(
            select(Item.storage_location_id).where(Item.id == item_id)
        )
        assert final in (targets[0].id, targets[1].id), (
            f'the record stands on {final}, not one of the two shelves it was moved to'
        )
        assert await db.scalar(
            select(Item.quantity).where(Item.id == item_id)
        ) == Decimal('10'), (
            'the moves left the record holding something other than its 10 units'
        )

    async def test_the_reconciliation_is_quiet_afterwards(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        """The job compares each shelf with what the ledger moved onto it.

        The drift the two moves left was permanent and unattributable: the
        report could see the difference and not which shelf the goods were
        meant to reach, so it stayed red until somebody went in by hand.
        """
        from app.services.analytics.reconciliation import get_reconciliation_async

        db = real_async_db_session
        org_id = async_test_household.id
        await self._two_moves_at_once(
            db, org_id, async_test_user, async_test_storage_location
        )

        await db.rollback()  # read the committed state, not this session's
        report = await get_reconciliation_async(db, org_id)

        assert report.quant_move_drift_count == 0, report
        assert report.quant_move_drift_total == Decimal('0'), report


@pytest.mark.integration
@pytest.mark.asyncio
class TestTwoBulkMoves:
    """Two batches moving one record carry the same holding off one shelf twice.

    The batch door reads its records in one unlocked select and
    ``_update_one_async`` captures each record's shelf and number from that
    read, so a shelf-only batch carries a holding somebody else may have
    already carried away. The door now takes the records' stock lock before
    its loop, quantity change or not; this holds it to that the same way the
    single edit's probe next door does.
    """

    async def _two_bulk_moves_at_once(
        self,
        db: AsyncSession,
        org_id: UUID,
        user,
        source: StorageLocation,
    ) -> tuple[UUID, ProductTemplate, list[StorageLocation]]:
        """Two sessions that fetched the record from one shelf, then move it apart.

        Both reads happen before either batch locks anything. The sessions
        fetch the record first because the service's own select hands the
        identity map's object back and cannot refresh it: the lock is what
        has to read the row again.
        """
        template = await db.run_sync(lambda s: make_template(s, org_id, name='Mint'))
        item = await put_on_shelf(db, user, template, source.id, 10)
        item_id = item.id
        targets = [
            StorageLocation(
                organization_id=org_id,
                name=f'QA bulk shelf {index} {uuid4().hex[:6]}',
                created_by=user.id,
            )
            for index in range(2)
        ]
        db.add_all(targets)
        await db.commit()

        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        read_by = [asyncio.Event(), asyncio.Event()]

        async def edit(slot: int, to_location_id: UUID) -> None:
            async with factory() as session:
                record = await session.get(Item, item_id)
                assert record is not None
                read_by[slot].set()
                await asyncio.wait_for(read_by[1 - slot].wait(), timeout=5)
                await bulk_update_items(
                    session,
                    ItemBulkUpdate(
                        item_ids=[item_id],
                        update_data=ItemUpdate(location_id=to_location_id),
                    ),
                    make_user_context(org_id, user.id),
                )
                await session.commit()

        try:
            await asyncio.gather(edit(0, targets[0].id), edit(1, targets[1].id))
        finally:
            await engine.dispose()
        return item_id, template, targets

    async def test_each_shelf_still_equals_what_the_ledger_moved(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        db = real_async_db_session
        org_id = async_test_household.id
        source = async_test_storage_location
        item_id, template, targets = await self._two_bulk_moves_at_once(
            db, org_id, async_test_user, source
        )

        await db.rollback()
        for location in (source, *targets):
            held = await _held(db, template.id, location.id)
            moved = await _net_moved(db, org_id, template.id, location.id)
            assert held == moved, (
                f'{location.name}: the shelf holds {held} but the ledger moved '
                f'{moved} — the two batch moves carried the same holding off '
                'one shelf'
            )
        final = await db.scalar(
            select(Item.storage_location_id).where(Item.id == item_id)
        )
        assert final in (targets[0].id, targets[1].id), (
            f'the record stands on {final}, not one of the two shelves it was moved to'
        )
        assert await db.scalar(
            select(Item.quantity).where(Item.id == item_id)
        ) == Decimal('10'), (
            'the moves left the record holding something other than its 10 units'
        )
