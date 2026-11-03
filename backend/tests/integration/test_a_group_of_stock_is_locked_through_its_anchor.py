"""A change to a group of stock waits on the group's anchor.

The stock lock used to lock the quants an operation was about to write. A
group nobody had stocked yet had no quant, so the first receipt to a shelf
locked nothing: two of them at once both went on to insert, and only the
quant's unique key, with a retry, kept them from leaving two rows. The
records are the only count now, and the quants are gone.

Every group now has an anchor — a row with no quantity per product and
shelf — which the lock creates when it is missing and then locks. Each test
below puts stock on the shelves the way the application does, through
records, holds one transaction inside the lock and asks the database where
the other one stopped: at the anchor, and not nowhere.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.public_api import core_api
from app.models.stock_anchor import StockAnchor
from app.models.storage_location import StorageLocation
from app.services._stock_quant_ops import take_from_the_records_async

from ._core_api_helpers import make_template
from ._shelf import put_on_shelf, shelf_keeper

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_DEADLOCK = '40P01'

# Only for a change stuck on something else: nothing here takes this long, and
# no test passes or fails on how close it comes.
_NEVER_ARRIVES_AFTER = 120.0


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


async def _pid(session: AsyncSession) -> int:
    return int(await session.scalar(text('SELECT pg_backend_pid()')))


async def _waiting_on(engine: AsyncEngine, pid: int, racer: asyncio.Task[Any]) -> str:
    """Which stock table *pid* has got to, once it is blocked on a lock.

    ``pg_stat_activity`` can still show the statement before the one that
    waits, so the answer is read off the locks the transaction holds: one
    stopped at an anchor holds a lock on ``stock_anchors``. (A quant it got
    past the anchors to lock was the other answer, while there were quants.)

    However long *racer* takes to get there, the answer is still to come until
    it has finished. If it raised, that exception is the answer.
    """
    deadline = time.monotonic() + _NEVER_ARRIVES_AFTER
    async with engine.connect() as conn:
        while not racer.done() and time.monotonic() < deadline:
            blocked = await conn.scalar(
                text('SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted'),
                {'pid': pid},
            )
            if blocked:
                held = set(
                    (
                        await conn.execute(
                            text(
                                'SELECT relation::regclass::text, mode FROM pg_locks '
                                "WHERE pid = :pid AND granted AND locktype = 'relation'"
                            ),
                            {'pid': pid},
                        )
                    ).tuples()
                )
                if any(relation == 'stock_anchors' for relation, _ in held):
                    return 'stock_anchors'
                return f'neither table: {sorted(held)}'
            await asyncio.sleep(0.05)
    if racer.done():
        racer.result()
    return 'not waiting on any lock'


def _sqlstate(exc: BaseException) -> str | None:
    seen: BaseException | None = exc
    while seen is not None:
        code = getattr(seen, 'sqlstate', None) or getattr(seen, 'pgcode', None)
        if isinstance(code, str):
            return code
        seen = getattr(seen, 'orig', None) or seen.__cause__
    return None


async def _shelf(
    db: AsyncSession, org_id: uuid.UUID, created_by, name: str
) -> uuid.UUID:
    shelf = StorageLocation(organization_id=org_id, created_by=created_by, name=name)
    db.add(shelf)
    await db.flush()
    return shelf.id


async def _on_hand(
    db: AsyncSession, org_id: uuid.UUID, template_id: uuid.UUID
) -> dict[uuid.UUID, Decimal]:
    """What the records put on each shelf, read from the records' view."""
    rows = await db.execute(
        text(
            'SELECT storage_location_id, sum(quantity) '
            'FROM stock_quants_from_records '
            'WHERE organization_id = :org AND product_template_id = :template '
            'GROUP BY storage_location_id'
        ),
        {'org': org_id, 'template': template_id},
    )
    return dict(rows.tuples().all())


async def _anchors(db: AsyncSession, org_id: uuid.UUID, template_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(StockAnchor)
            .where(
                StockAnchor.organization_id == org_id,
                StockAnchor.product_template_id == template_id,
            )
        )
    )


@pytest.fixture
async def engine():
    # A lock that nothing here will release must fail the test, not hang it:
    # without the anchors, a second receipt goes ahead unblocked, and the
    # first then waits on a transaction the test commits only after the
    # first is done — a circle the database cannot see, since one side is
    # idle, not waiting. Every wait the tests mean is over in seconds.
    engine = create_async_engine(
        _async_test_url(),
        echo=False,
        poolclass=NullPool,
        connect_args={
            'server_settings': {'lock_timeout': f'{int(_NEVER_ARRIVES_AFTER)}s'}
        },
    )
    yield engine
    await engine.dispose()


async def _card(db: AsyncSession, org_id: uuid.UUID):
    """A product and someone to shelve it, committed for the sessions below."""
    template = await db.run_sync(
        lambda s: make_template(s, org_id, name=f'Lentils {uuid.uuid4().hex[:6]}')
    )
    keeper = await shelf_keeper(db, org_id)
    await db.commit()
    return template, keeper


async def test_a_second_change_that_fails_reports_its_own_failure(
    real_async_db_session: AsyncSession,
    engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession)
    async with factory() as second:
        second_pid = await _pid(second)
        failing = asyncio.create_task(second.execute(text('SELECT 1 / 0')))
        with pytest.raises(DBAPIError, match='division by zero'):
            await _waiting_on(engine, second_pid, failing)


async def test_two_first_arrivals_on_an_empty_shelf_queue_on_its_anchor(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    """Two records carried onto a shelf that has never held their product.

    The empty shelf holds nothing either arrival could lock. The first creates
    the shelf's anchor; the second waits on it and then finds what the first
    put there.
    """
    db = real_async_db_session
    org_id, created_by = async_test_household.id, async_test_storage_location.created_by
    first_shelf = async_test_storage_location.id
    second_shelf = await _shelf(db, org_id, created_by, 'Second')
    empty = await _shelf(db, org_id, created_by, 'Empty')
    template, keeper = await _card(db, org_id)
    template_id = template.id
    from_first = (await put_on_shelf(db, keeper, template, first_shelf, 3)).id
    from_second = (await put_on_shelf(db, keeper, template, second_shelf, 4)).id
    await db.commit()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as first, factory() as second:
        await core_api.items.transfer_async(
            first, org_id, from_first, empty, user_id=keeper.id
        )
        second_pid = await _pid(second)
        second_arrival = asyncio.create_task(
            core_api.items.transfer_async(
                second, org_id, from_second, empty, user_id=keeper.id
            )
        )
        waiting_on = await _waiting_on(engine, second_pid, second_arrival)
        await first.commit()
        await asyncio.wait_for(second_arrival, timeout=_NEVER_ARRIVES_AFTER)
        await second.commit()

    assert waiting_on == 'stock_anchors', waiting_on
    db.expire_all()
    assert await _on_hand(db, org_id, template_id) == {empty: Decimal('7')}
    assert await _anchors(db, org_id, template_id) == 3


async def test_two_receipts_naming_two_new_shelves_in_opposite_orders_queue(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    db = real_async_db_session
    org_id, created_by = async_test_household.id, async_test_storage_location.created_by
    left = await _shelf(db, org_id, created_by, 'Left')
    right = await _shelf(db, org_id, created_by, 'Right')
    template, keeper = await _card(db, org_id)
    template_id = template.id
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def receive(session: AsyncSession, shelves: list[uuid.UUID]) -> None:
        # Both shelves named up front, as a document names its lines.
        await core_api.stock.lock_async(
            session, org_id, keys=[(template_id, shelf) for shelf in shelves]
        )
        for shelf in shelves:
            await put_on_shelf(session, keeper, template, shelf, 1)

    async with factory() as one, factory() as two:
        await core_api.stock.lock_async(
            one, org_id, keys=[(template_id, left), (template_id, right)]
        )
        two_pid = await _pid(two)
        second = asyncio.create_task(receive(two, [right, left]))
        waiting_on = await _waiting_on(engine, two_pid, second)
        await receive(one, [left, right])
        await one.commit()
        await asyncio.wait_for(second, timeout=_NEVER_ARRIVES_AFTER)
        await two.commit()

    assert waiting_on == 'stock_anchors', waiting_on
    db.expire_all()
    assert await _on_hand(db, org_id, template_id) == {
        left: Decimal('2'),
        right: Decimal('2'),
    }
    assert await _anchors(db, org_id, template_id) == 2


async def test_a_shelf_locked_late_is_a_detected_deadlock_not_wrong_stock(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    """Naming the second shelf only when it is reached breaks the one order.

    The lock can keep two writers apart only in the order it is given all the
    keys at once. Two receipts that each shelve on one shelf, and then on the
    other's, close a circle. The database finds it and aborts one of them;
    what the other wrote is whole, and the aborted one wrote nothing.
    """
    db = real_async_db_session
    org_id, created_by = async_test_household.id, async_test_storage_location.created_by
    left = await _shelf(db, org_id, created_by, 'Left')
    right = await _shelf(db, org_id, created_by, 'Right')
    template, keeper = await _card(db, org_id)
    template_id = template.id
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as one, factory() as two:
        await put_on_shelf(one, keeper, template, left, 1)
        await put_on_shelf(two, keeper, template, right, 1)
        one_pid = await _pid(one)
        first = asyncio.create_task(put_on_shelf(one, keeper, template, right, 1))
        await _waiting_on(engine, one_pid, first)
        second = asyncio.create_task(put_on_shelf(two, keeper, template, left, 1))
        outcomes = await asyncio.wait_for(
            asyncio.gather(first, second, return_exceptions=True),
            timeout=_NEVER_ARRIVES_AFTER,
        )
        aborted = [
            session
            for session, outcome in zip((one, two), outcomes, strict=True)
            if isinstance(outcome, DBAPIError) and _sqlstate(outcome) == _DEADLOCK
        ]
        assert len(aborted) == 1, outcomes
        await aborted[0].rollback()
        survivor = two if aborted[0] is one else one
        await survivor.commit()

    db.expire_all()
    assert await _on_hand(db, org_id, template_id) == {
        left: Decimal('1'),
        right: Decimal('1'),
    }
    assert await _anchors(db, org_id, template_id) == 2


async def test_a_lock_on_every_shelf_and_a_move_off_one_of_them_queue(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    """Every shelf of a product locks the anchors that exist; a move waits on them.

    A document and a production run take a product from whichever shelves
    hold it, so they lock the product on every shelf. A record carried off
    one of those shelves to a shelf that has never held the product creates
    the new shelf's anchor and then waits, and the two leave the stock adding
    up.
    """
    db = real_async_db_session
    org_id, created_by = async_test_household.id, async_test_storage_location.created_by
    first_shelf = async_test_storage_location.id
    second_shelf = await _shelf(db, org_id, created_by, 'Second')
    new_shelf = await _shelf(db, org_id, created_by, 'New')
    template, keeper = await _card(db, org_id)
    template_id = template.id
    on_the_first = (await put_on_shelf(db, keeper, template, first_shelf, 10)).id
    on_the_second = (await put_on_shelf(db, keeper, template, second_shelf, 10)).id
    await db.commit()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as every_shelf, factory() as mover:
        await core_api.stock.lock_async(every_shelf, org_id, keys=[(template_id, None)])
        mover_pid = await _pid(mover)
        move = asyncio.create_task(
            core_api.items.transfer_async(
                mover, org_id, on_the_first, new_shelf, user_id=keeper.id
            )
        )
        waiting_on = await _waiting_on(engine, mover_pid, move)
        await core_api.items.update_quantity_async(
            every_shelf, org_id, on_the_second, Decimal('7'), user_id=keeper.id
        )
        await every_shelf.commit()
        await asyncio.wait_for(move, timeout=_NEVER_ARRIVES_AFTER)
        await mover.commit()

    assert waiting_on == 'stock_anchors', waiting_on
    db.expire_all()
    assert await _on_hand(db, org_id, template_id) == {
        second_shelf: Decimal('7'),
        new_shelf: Decimal('10'),
    }
    assert await _anchors(db, org_id, template_id) == 3


async def test_two_records_typed_onto_an_empty_shelf_queue_on_its_anchor(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    """A record typed in reaches the shelf through the single-group receipt.

    Nothing locks up front on that path: the receipt locks its own group's
    anchor, so the second record waits there for the first.
    """
    db = real_async_db_session
    org_id, created_by = async_test_household.id, async_test_storage_location.created_by
    empty = await _shelf(db, org_id, created_by, 'Empty')
    template, keeper = await _card(db, org_id)
    template_id = template.id
    await db.commit()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as first, factory() as second:
        await put_on_shelf(first, keeper, template, empty, 3)
        second_pid = await _pid(second)
        second_record = asyncio.create_task(
            put_on_shelf(second, keeper, template, empty, 4)
        )
        waiting_on = await _waiting_on(engine, second_pid, second_record)
        await first.commit()
        await asyncio.wait_for(second_record, timeout=_NEVER_ARRIVES_AFTER)
        await second.commit()

    assert waiting_on == 'stock_anchors', waiting_on
    db.expire_all()
    assert await _on_hand(db, org_id, template_id) == {empty: Decimal('7')}
    assert await _anchors(db, org_id, template_id) == 1


async def test_two_records_of_one_group_taken_down_at_once_queue_on_its_anchor(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    """A record's quantity lowered by hand leaves through the single-group issue.

    Nothing locks up front on that path either: the issue locks its own
    group's anchor, so a second record of the group lowered at the same time
    waits there.
    """
    db = real_async_db_session
    org_id, shelf = async_test_household.id, async_test_storage_location.id
    template, keeper = await _card(db, org_id)
    template_id = template.id
    one = (await put_on_shelf(db, keeper, template, shelf, 5)).id
    other = (await put_on_shelf(db, keeper, template, shelf, 5)).id
    await db.commit()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as first, factory() as second:
        await core_api.items.update_quantity_async(
            first, org_id, one, Decimal('2'), user_id=keeper.id
        )
        second_pid = await _pid(second)
        second_change = asyncio.create_task(
            core_api.items.update_quantity_async(
                second, org_id, other, Decimal('4'), user_id=keeper.id
            )
        )
        waiting_on = await _waiting_on(engine, second_pid, second_change)
        await first.commit()
        await asyncio.wait_for(second_change, timeout=_NEVER_ARRIVES_AFTER)
        await second.commit()

    assert waiting_on == 'stock_anchors', waiting_on
    db.expire_all()
    assert await _on_hand(db, org_id, template_id) == {shelf: Decimal('6')}


async def test_the_movement_pass_waits_on_the_anchor_before_it_writes(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    """``post_movement_async`` takes the group's anchor before it writes.

    The movement pass is a door of its own — a document executor, a
    production run and a module's stock write all call it — so the lock it
    takes is what keeps it from racing the record's own posting on the same
    shelf. A second transaction holding the anchor must stop it at the
    anchor, not nowhere.
    """
    db = real_async_db_session
    org_id = async_test_household.id
    shelf = async_test_storage_location.id
    template, keeper = await _card(db, org_id)
    template_id = template.id
    await db.commit()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as first, factory() as second:
        await core_api.stock.lock_async(first, org_id, keys=[(template_id, shelf)])
        second_pid = await _pid(second)
        arrival = asyncio.create_task(
            core_api.stock.post_movement_async(
                second,
                org_id,
                template_id,
                Decimal('2'),
                to_location_id=shelf,
                reference_type='item',
                reference_id=uuid.uuid4(),
                created_by=keeper.id,
            )
        )
        waiting_on = await _waiting_on(engine, second_pid, arrival)
        await first.commit()
        await asyncio.wait_for(arrival, timeout=_NEVER_ARRIVES_AFTER)
        await second.commit()

    assert waiting_on == 'stock_anchors', waiting_on


async def test_an_every_shelf_draw_keeps_the_anchors_it_locked_before_the_plan(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    """A shelf stocked while the every-shelf draw is locking is locked late.

    The every-shelf lock sees the anchors that exist when it runs. A first
    receipt on another shelf may commit while that lock waits, and the plan
    then reads and draws on the new shelf too; the draw locks that shelf and
    re-plans. The anchors the first lock took must stay in the set the
    re-plan is checked against. A draw that forgets them sees one of the two
    shelves missing from the held set on every pass, locks it, forgets the
    other, and never settles.
    """
    db = real_async_db_session
    org_id, created_by = async_test_household.id, async_test_storage_location.created_by
    first_shelf = async_test_storage_location.id
    second_shelf = await _shelf(db, org_id, created_by, 'Second')
    template, keeper = await _card(db, org_id)
    template_id = template.id
    await put_on_shelf(db, keeper, template, first_shelf, 1)
    await db.commit()
    first_anchor = await db.scalar(
        select(StockAnchor.id).where(
            StockAnchor.organization_id == org_id,
            StockAnchor.product_template_id == template_id,
            StockAnchor.storage_location_id == first_shelf,
        )
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as holder, factory() as drawer, factory() as arrival:
        await holder.execute(
            text('SELECT id FROM stock_anchors WHERE id = :id FOR UPDATE'),
            {'id': first_anchor},
        )
        drawer_pid = await _pid(drawer)
        draw = asyncio.create_task(
            take_from_the_records_async(
                drawer, org_id, template_id, None, Decimal('2'), user_id=keeper.id
            )
        )
        waiting_on = await _waiting_on(engine, drawer_pid, draw)
        assert waiting_on == 'stock_anchors', waiting_on
        # The shelf the first lock cannot see: its anchor is created and its
        # stock committed while the every-shelf lock is still waiting.
        await put_on_shelf(arrival, keeper, template, second_shelf, 1)
        await arrival.commit()
        await holder.commit()
        taken = await asyncio.wait_for(draw, timeout=_NEVER_ARRIVES_AFTER)
        await drawer.commit()

    assert sum((entry.consumed for entry in taken), Decimal('0')) == Decimal('2')
    db.expire_all()
    assert await _on_hand(db, org_id, template_id) == {
        first_shelf: Decimal('0'),
        second_shelf: Decimal('0'),
    }
