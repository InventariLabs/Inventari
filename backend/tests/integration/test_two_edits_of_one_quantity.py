"""Two people editing one quantity leave the bridge standing.

``PUT /items/{id}`` read the record through ``get_item_or_404_async`` — no
lock — and the update path then set ``item.quantity = new`` and computed
``delta = new - old`` from that unlocked read. Two edits in flight: both
deltas reach the quants (each under the quant's own row lock, so the quants
add up), and ``Item.quantity`` ends up at whichever write landed last. The
bridge between the cache and the truth is broken from then on, and the
reconciliation reports a drift it cannot heal — it can see the difference,
not which of the two numbers was meant.

The quants are gone; each edit's delta is a movement in the ledger now, so
the same race leaves the record and the ledger apart, and the reconciliation's
shelf-versus-ledger pair reports it.

The locking read already existed next door (``get_by_id_for_update_async``,
used by the scanning paths). This holds the edit path to it. The edits here
travel through the endpoint, because the lock is the route's decision — it
reads ``item_in.quantity is not None`` to pick the locking read, and a test
that locked by hand would stay green the day that condition broke.

The batch door, ``bulk_update_items``, read its records unlocked too and
captured each one's old number from that read, so two batches of one
selection posted two deltas measured against the same stale number. Its
probe lives here beside the single edit's: the two doors write the same
bridge and must answer for it the same way.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.item import Item
from app.models.stock_move import StockMove
from app.models.user import User
from app.schemas.item import ItemBulkUpdate, ItemUpdate
from app.services.items import bulk_update_items, update_item
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf

from ._core_api_helpers import make_template, make_user_context


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestConcurrentQuantityEdits:
    async def test_the_record_still_equals_what_the_ledger_moved(
        self,
        real_async_db_session: AsyncSession,
        real_async_client: AsyncClient,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        db = real_async_db_session
        org_id = async_test_household.id
        location_id = async_test_storage_location.id
        template = await db.run_sync(
            lambda s: make_template(s, org_id, name='Kawa mielona')
        )
        item = await put_on_shelf(db, async_test_user, template, location_id, 10)
        item_id = item.id
        await db.commit()

        async def edit(new_quantity: str) -> None:
            response = await real_async_client.put(
                f'/api/v1/items/{item_id}',
                json={'quantity': new_quantity},
                headers=_auth(async_test_user),
            )
            assert response.status_code == 200, response.text

        try:
            await asyncio.gather(edit('30'), edit('50'))
        finally:
            engine = create_async_engine(
                _async_test_url(), echo=False, poolclass=NullPool
            )
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with factory() as verify:
                cached = await verify.scalar(
                    select(Item.quantity).where(Item.id == item_id)
                )
                arrived, left = [
                    await verify.scalar(
                        select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
                            StockMove.organization_id == org_id,
                            StockMove.product_template_id == template.id,
                            column == location_id,
                        )
                    )
                    for column in (
                        StockMove.to_location_id,
                        StockMove.from_location_id,
                    )
                ]
            await engine.dispose()

        moved = arrived - left
        assert cached == moved, (
            f'Item.quantity={cached} but the ledger moved {moved} — the two '
            'edits computed their delta from the same stale read'
        )
        assert cached in (Decimal('30'), Decimal('50')), cached

    async def test_the_reconciliation_is_quiet_afterwards(
        self,
        real_async_db_session: AsyncSession,
        real_async_client: AsyncClient,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        """The drift the two edits left was permanent and unattributable.

        The job compares the shelf with what the ledger moved; it can see
        the difference and not which of the two numbers anybody meant, so
        the report stayed red until somebody went in by hand.
        """
        from app.services.analytics.reconciliation import get_reconciliation_async

        db = real_async_db_session
        org_id = async_test_household.id
        location_id = async_test_storage_location.id
        template = await db.run_sync(lambda s: make_template(s, org_id, name='Herbata'))
        item = await put_on_shelf(db, async_test_user, template, location_id, 10)
        item_id = item.id
        await db.commit()

        async def edit(new_quantity: str) -> None:
            response = await real_async_client.put(
                f'/api/v1/items/{item_id}',
                json={'quantity': new_quantity},
                headers=_auth(async_test_user),
            )
            assert response.status_code == 200, response.text

        await asyncio.gather(edit('25'), edit('40'))

        await db.rollback()  # read the committed state, not this session's
        report = await get_reconciliation_async(db, org_id)

        assert report.quant_move_drift_count == 0, report
        assert report.quant_move_drift_total == Decimal('0'), report


@pytest.mark.integration
@pytest.mark.asyncio
class TestTwoServiceEdits:
    """Two edits that read the record before either one writes it.

    The route takes the row lock when it fetches, and the class above pins
    that decision. The door itself must not lean on the route: a caller that
    already holds the record — ``core_api.items.update_async``, a module, the
    batch path — read the number before either edit locked, and both edits
    measured their delta against that same stale read. Here both sessions
    load the record, meet, and only then edit: the interleaving the door has
    to survive on its own.
    """

    async def test_the_record_still_equals_what_the_ledger_moved(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        db = real_async_db_session
        org_id = async_test_household.id
        location_id = async_test_storage_location.id
        template = await db.run_sync(lambda s: make_template(s, org_id, name='Cocoa'))
        item = await put_on_shelf(db, async_test_user, template, location_id, 10)
        item_id = item.id
        await db.commit()

        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        read_by = [asyncio.Event(), asyncio.Event()]

        async def edit(slot: int, new_quantity: str) -> None:
            async with factory() as session:
                record = await session.get(Item, item_id)
                assert record is not None
                read_by[slot].set()
                await asyncio.wait_for(read_by[1 - slot].wait(), timeout=5)
                await update_item(
                    session,
                    record,
                    ItemUpdate(quantity=Decimal(new_quantity)),
                    make_user_context(org_id, async_test_user.id),
                )
                await session.commit()

        try:
            await asyncio.gather(edit(0, '5'), edit(1, '7'))
        finally:
            await engine.dispose()

        await db.rollback()
        cached = await db.scalar(select(Item.quantity).where(Item.id == item_id))
        arrived, left = [
            await db.scalar(
                select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
                    StockMove.organization_id == org_id,
                    StockMove.product_template_id == template.id,
                    column == location_id,
                )
            )
            for column in (
                StockMove.to_location_id,
                StockMove.from_location_id,
            )
        ]
        moved = arrived - left
        assert cached == moved, (
            f'Item.quantity={cached} but the ledger moved {moved} — the two '
            'edits computed their delta from the same stale read'
        )
        assert cached in (Decimal('5'), Decimal('7')), cached


@pytest.mark.integration
@pytest.mark.asyncio
class TestTwoBulkEdits:
    """Two batches editing one record measure their deltas apart.

    The batch door reads its records in one unlocked select and captures
    each record's old number from that read. Two batches holding the record
    from before either one locked it both measured their delta against the
    same stale number and both posted it, so the record and the ledger
    parted the same way the single edit's two doors did.

    The sessions here load the record before they call the service, which is
    the shape the defect needs: the service's own select hands the identity
    map's object back and cannot refresh it, so the lock is what has to read
    the row again.
    """

    async def test_the_record_still_equals_what_the_ledger_moved(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        db = real_async_db_session
        org_id = async_test_household.id
        location_id = async_test_storage_location.id
        template = await db.run_sync(lambda s: make_template(s, org_id, name='Mąka'))
        item = await put_on_shelf(db, async_test_user, template, location_id, 10)
        item_id = item.id
        await db.commit()

        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        read_by = [asyncio.Event(), asyncio.Event()]

        async def edit(slot: int, new_quantity: str) -> None:
            async with factory() as session:
                record = await session.get(Item, item_id)
                assert record is not None
                read_by[slot].set()
                await asyncio.wait_for(read_by[1 - slot].wait(), timeout=5)
                await bulk_update_items(
                    session,
                    ItemBulkUpdate(
                        item_ids=[item_id],
                        update_data=ItemUpdate(quantity=Decimal(new_quantity)),
                    ),
                    make_user_context(org_id, async_test_user.id),
                )
                await session.commit()

        try:
            await asyncio.gather(edit(0, '5'), edit(1, '7'))
        finally:
            await engine.dispose()

        await db.rollback()
        cached = await db.scalar(select(Item.quantity).where(Item.id == item_id))
        arrived, left = [
            await db.scalar(
                select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
                    StockMove.organization_id == org_id,
                    StockMove.product_template_id == template.id,
                    column == location_id,
                )
            )
            for column in (
                StockMove.to_location_id,
                StockMove.from_location_id,
            )
        ]
        moved = arrived - left
        assert cached == moved, (
            f'Item.quantity={cached} but the ledger moved {moved} — the two '
            'batch edits computed their delta from the same stale read'
        )
        assert cached in (Decimal('5'), Decimal('7')), cached


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheLockingReadReadsTheRow:
    async def test_a_record_already_in_the_session_comes_back_as_committed(
        self,
        real_async_db_session: AsyncSession,
        async_test_item,
    ):
        """Locking the row is half of it; the object has to show the row too.

        A session that had loaded the record before asking for the lock got
        the same object back from its identity map, still holding the number
        it had read earlier — another transaction's committed write was
        invisible to the one caller that had waited for it. Measured without
        ``populate_existing``: the locked read returned 2.000 over a committed
        77.
        """
        from sqlalchemy import update

        from app.services.items._query_get import get_by_id_for_update_async

        await real_async_db_session.commit()
        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with factory() as reader:
                loaded = await reader.scalar(
                    select(Item).where(Item.id == async_test_item.id)
                )
                assert loaded is not None
                async with factory() as writer:
                    await writer.execute(
                        update(Item)
                        .where(Item.id == async_test_item.id)
                        .values(quantity=Decimal('77'))
                    )
                    await writer.commit()

                locked = await get_by_id_for_update_async(
                    reader, async_test_item.organization_id, async_test_item.id
                )
                assert locked is not None
                seen = locked.quantity
                await reader.rollback()
        finally:
            await engine.dispose()

        assert seen == Decimal('77'), (
            f'the locked read showed {seen} over a committed 77'
        )
