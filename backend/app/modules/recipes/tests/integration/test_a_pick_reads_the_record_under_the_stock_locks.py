"""A pick, and its undo, write a record they read under the stock locks.

A recipe pick and its undo write a record's quantity as an absolute number,
worked out from what the record held. So the record is read under the locks
every writer of the stock takes, and in their order: the product's groups
first, then the record's row. A number read before the locks loses whatever
was written in between, and a row held before the groups deadlocks with a
door that holds the group and waits for the row.

Each test stops one operation between its read and its write, starts another
on the same record, and lets both finish.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.contracts import UserContextDTO
from app.core.public_api import core_api
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.modules.recipes import _picking_scan
from app.modules.recipes.picking_service import scan_item_in_picking, undo_pick
from app.schemas.item import ItemConsumeRequest
from app.services.items import _consumed_place, consume_item
from tests.integration._cooking import a_picking_session
from tests.integration._core_api_helpers import make_template
from tests.integration._shelf import put_on_shelf, shelf_keeper
from tests.integration.test_a_group_of_stock_is_locked_through_its_anchor import (
    _NEVER_ARRIVES_AFTER,
    _async_test_url,
    _pid,
    _waiting_on,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_Door = Callable[[AsyncSession], Awaitable[object]]


@pytest.fixture(autouse=True)
def a_unit_on_every_recipe_line() -> None:
    """The recipes here are written straight to the session, with their unit."""


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
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


async def _label(db: AsyncSession, record_id: uuid.UUID, barcode: str) -> None:
    """Give the record a barcode of its own; one put on the shelf has none."""
    record = await db.get(Item, record_id)
    assert record is not None
    record.barcode = barcode


async def _ten_on_the_shelf(
    db: AsyncSession, org_id: uuid.UUID, shelf: uuid.UUID
) -> tuple[UserContextDTO, uuid.UUID, uuid.UUID, str]:
    """A record of ten pieces; returns who acts, its product, itself, its barcode."""
    barcode = uuid.uuid4().hex[:13]
    template = await db.run_sync(
        lambda s: make_template(s, org_id, name=f'Rice {barcode}')
    )
    pieces = await db.scalar(select(Uom.id).where(Uom.symbol == 'pcs'))
    template.barcode = barcode
    template.uom_id = pieces
    await db.flush()
    keeper = await shelf_keeper(db, org_id)
    record = await put_on_shelf(db, keeper, template, shelf, 10)
    await db.commit()
    return keeper, template.id, record.id, barcode


def _scan(
    org_id: uuid.UUID,
    keeper: UserContextDTO,
    session_id: uuid.UUID,
    *,
    item_id: uuid.UUID | None = None,
    barcode: str | None = None,
) -> _Door:
    async def door(db: AsyncSession) -> None:
        answer = await scan_item_in_picking(
            db,
            session_id,
            org_id,
            keeper,
            barcode=barcode,
            item_id=item_id,
        )
        assert answer.status == 'picked', answer

    return door


def _use(keeper: UserContextDTO, record_id: uuid.UUID, quantity: int) -> _Door:
    async def door(db: AsyncSession) -> None:
        record = await db.get(Item, record_id)
        assert record is not None
        await consume_item(
            db, record, ItemConsumeRequest(quantity=Decimal(quantity)), keeper
        )

    return door


async def _the_second_starts_while_the_first_is_stopped(
    engine: AsyncEngine, owner: Any, name: str, first: _Door, second: _Door
) -> None:
    """Run both, each committing its own work.

    *first* is stopped at its first call of ``owner.name`` until *second* has
    either finished or queued behind a lock.
    """
    reached = asyncio.Event()
    carry_on = asyncio.Event()
    real = getattr(owner, name)

    async def stopped(*args: Any, **kwargs: Any) -> Any:
        if not reached.is_set():
            reached.set()
            await carry_on.wait()
        return await real(*args, **kwargs)

    async def committed(db: AsyncSession, door: _Door) -> None:
        try:
            await door(db)
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as one, factory() as two:
        with patch.object(owner, name, stopped):
            leading = asyncio.create_task(committed(one, first))
            arrival = asyncio.ensure_future(reached.wait())
            await asyncio.wait(
                {arrival, leading},
                timeout=_NEVER_ARRIVES_AFTER,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if leading.done():
                leading.result()
            assert reached.is_set()
            pid = await _pid(two)
            following = asyncio.create_task(committed(two, second))
            await _waiting_on(engine, pid, following)
            carry_on.set()
            outcomes = await asyncio.wait_for(
                asyncio.gather(leading, following, return_exceptions=True),
                _NEVER_ARRIVES_AFTER,
            )
    assert [o for o in outcomes if o is not None] == []


async def _held(db: AsyncSession, record_id: uuid.UUID) -> Decimal:
    db.expire_all()
    record = await db.get(Item, record_id)
    assert record is not None
    return record.quantity


@pytest.mark.parametrize('scanned', ['record', 'record-barcode', 'product-barcode'])
async def test_two_picks_from_one_record_at_once_take_both(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_storage_location: StorageLocation,
    engine: AsyncEngine,
    scanned: str,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    keeper, template_id, record_id, barcode = await _ten_on_the_shelf(
        db, org_id, async_test_storage_location.id
    )
    first, _ = await a_picking_session(db, keeper, template_id, Decimal('2'))
    second, _ = await a_picking_session(db, keeper, template_id, Decimal('3'))
    if scanned == 'record-barcode':
        await _label(db, record_id, barcode)
    await db.commit()
    by = {'item_id': record_id} if scanned == 'record' else {'barcode': barcode}

    await _the_second_starts_while_the_first_is_stopped(
        engine,
        _picking_scan,
        'consume_for_picking',
        _scan(org_id, keeper, first, **by),
        _scan(org_id, keeper, second, **by),
    )

    assert await _held(db, record_id) == Decimal('5')


async def test_a_pick_and_a_use_of_one_record_at_once_both_go_through(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_storage_location: StorageLocation,
    engine: AsyncEngine,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    keeper, template_id, record_id, _ = await _ten_on_the_shelf(
        db, org_id, async_test_storage_location.id
    )
    session_id, _ = await a_picking_session(db, keeper, template_id, Decimal('2'))
    await db.commit()

    await _the_second_starts_while_the_first_is_stopped(
        engine,
        _picking_scan,
        'consume_for_picking',
        _scan(org_id, keeper, session_id, item_id=record_id),
        _use(keeper, record_id, 3),
    )

    assert await _held(db, record_id) == Decimal('5')


async def test_an_undone_pick_keeps_what_was_used_meanwhile(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_storage_location: StorageLocation,
    engine: AsyncEngine,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    keeper, template_id, record_id, _ = await _ten_on_the_shelf(
        db, org_id, async_test_storage_location.id
    )
    session_id, ingredient_id = await a_picking_session(
        db, keeper, template_id, Decimal('2')
    )
    await _scan(org_id, keeper, session_id, item_id=record_id)(db)
    await db.commit()

    async def undo(session: AsyncSession) -> None:
        await undo_pick(session, session_id, org_id, ingredient_id)

    await _the_second_starts_while_the_first_is_stopped(
        engine,
        core_api.items,
        'update_quantity_async',
        undo,
        _use(keeper, record_id, 3),
    )

    assert await _held(db, record_id) == Decimal('7')


async def test_a_record_used_up_while_its_scan_waited_is_not_picked(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_storage_location: StorageLocation,
    engine: AsyncEngine,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    keeper, template_id, record_id, barcode = await _ten_on_the_shelf(
        db, org_id, async_test_storage_location.id
    )
    session_id, _ = await a_picking_session(db, keeper, template_id, Decimal('2'))
    await _label(db, record_id, barcode)
    await db.commit()
    answers: list[str] = []

    async def scan(session: AsyncSession) -> None:
        answer = await scan_item_in_picking(
            session, session_id, org_id, keeper, barcode=barcode, item_id=None
        )
        answers.append(answer.status)

    await _the_second_starts_while_the_first_is_stopped(
        engine,
        _consumed_place,
        'lock_shelf_change_async',
        _use(keeper, record_id, 10),
        scan,
    )

    assert answers == ['not_in_recipe']
    assert await _held(db, record_id) == Decimal('0')
