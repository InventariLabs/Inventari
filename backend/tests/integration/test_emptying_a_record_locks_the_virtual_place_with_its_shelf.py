"""A door that empties a record takes the virtual place's lock with its shelf's.

Taking the last unit of a record files it under one of the organization's
virtual places (Consumed, or Inventory Loss for a disposal), a group of the
same product with an anchor of its own. An operation that locks every shelf
of the product takes the anchors in ``id`` order, so it may take the virtual
place's before the shelf's. A door that holds the shelf and asks for the
virtual place only when it files the record deadlocks with it: each holds
what the other waits for, and the database aborts one of them.

Here the virtual place's anchor has the lower ``id``, the door is stopped
between taking its shelf and filing the record, and the other operation
queues behind it. Whatever the door holds by then, both must go through.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
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
from app.models.stock_anchor import StockAnchor
from app.models.storage_location import LocationUsage
from app.models.uom import Uom
from app.schemas.item import ItemConsumeRequest, ItemDiscardRequest
from app.services._stock_quant_ops import take_from_the_records_async
from app.services.items import _consumed_place, consume_item, discard_item
from app.services.items._open_package import use_partially_async
from app.services.storage._defaults import (
    ensure_virtual_locations_async,
    get_virtual_location_async,
)

from ._core_api_helpers import make_template
from ._shelf import put_on_shelf, shelf_keeper
from .test_a_group_of_stock_is_locked_through_its_anchor import (
    _NEVER_ARRIVES_AFTER,
    _async_test_url,
    _pid,
    _waiting_on,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def engine():
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


async def _draw(db, keeper, record, quantity):
    await take_from_the_records_async(
        db,
        keeper.organization_id,
        record.template_id,
        record.storage_location_id,
        quantity,
        user_id=keeper.id,
        file_when_emptied=True,
    )


async def _use(db, keeper, record, quantity):
    await consume_item(db, record, ItemConsumeRequest(quantity=quantity), keeper)


async def _dispose(db, keeper, record, quantity):
    await discard_item(
        db, record, ItemDiscardRequest(quantity=quantity, reason='spoiled'), keeper
    )


async def _finish_the_package(db, keeper, record, quantity):
    await use_partially_async(db, record, keeper, left=Decimal('0'))


async def _a_record_whose_place_locks_first(
    db: AsyncSession,
    org_id: uuid.UUID,
    home: uuid.UUID,
    usage: LocationUsage,
    quantity: int,
) -> tuple[UserContextDTO, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A record on *home*, its virtual place's anchor ahead of the shelf's.

    Returns who acts, the product, the virtual place and the record.
    """
    template = await db.run_sync(
        lambda s: make_template(s, org_id, name=f'Rice {uuid.uuid4().hex[:6]}')
    )
    keeper = await shelf_keeper(db, org_id)
    template_id = template.id
    await ensure_virtual_locations_async(db, str(org_id), str(keeper.id))
    place = await get_virtual_location_async(db, str(org_id), usage)
    assert place is not None
    place_id = place.id
    # The anchors are given their ids here so the order the lock takes them
    # in does not depend on which uuid the database happened to draw.
    for anchor_id, shelf in (
        (uuid.UUID(int=1), place_id),
        (uuid.UUID(int=2**100), home),
    ):
        db.add(
            StockAnchor(
                id=anchor_id,
                organization_id=org_id,
                product_template_id=template_id,
                storage_location_id=shelf,
            )
        )
    await db.flush()
    record = await put_on_shelf(db, keeper, template, home, quantity)
    record_id = record.id
    # A package is something counted in pieces.
    record.uom_id = await db.scalar(select(Uom.id).where(Uom.symbol == 'pcs'))
    await db.commit()
    return keeper, template_id, place_id, record_id


@pytest.mark.parametrize(
    ('door', 'usage', 'quantity'),
    [
        pytest.param(_draw, LocationUsage.CUSTOMER, 5, id='draw'),
        pytest.param(_use, LocationUsage.CUSTOMER, 5, id='use'),
        pytest.param(_dispose, LocationUsage.INVENTORY, 5, id='dispose'),
        pytest.param(_finish_the_package, LocationUsage.CUSTOMER, 1, id='package'),
    ],
)
async def test_a_door_that_files_a_record_and_a_lock_of_every_shelf_do_not_deadlock(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
    door,
    usage: LocationUsage,
    quantity: int,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    keeper, template_id, place_id, record_id = await _a_record_whose_place_locks_first(
        db, org_id, async_test_storage_location.id, usage, quantity
    )

    reached_the_filing = asyncio.Event()
    carry_on = asyncio.Event()
    lock_the_shelf_change = _consumed_place.lock_shelf_change_async

    async def stopped_before_the_filing(*args, **kwargs):
        reached_the_filing.set()
        await carry_on.wait()
        return await lock_the_shelf_change(*args, **kwargs)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    errors: list[BaseException] = []

    async with factory() as drain, factory() as every_shelf:
        held = await drain.get(Item, record_id)
        assert held is not None
        with patch.object(
            _consumed_place, 'lock_shelf_change_async', stopped_before_the_filing
        ):
            taking = asyncio.create_task(door(drain, keeper, held, Decimal(quantity)))
            filing = asyncio.ensure_future(reached_the_filing.wait())
            await asyncio.wait(
                {filing, taking},
                timeout=_NEVER_ARRIVES_AFTER,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if taking.done():
                taking.result()
            assert reached_the_filing.is_set()
            other_pid = await _pid(every_shelf)
            other = asyncio.create_task(
                core_api.stock.lock_async(
                    every_shelf, org_id, keys=[(template_id, None)]
                )
            )
            await _waiting_on(engine, other_pid, other)
            carry_on.set()
            try:
                await asyncio.wait_for(taking, _NEVER_ARRIVES_AFTER)
                await drain.commit()
            except DBAPIError as exc:
                errors.append(exc)
                await drain.rollback()
            try:
                await asyncio.wait_for(other, _NEVER_ARRIVES_AFTER)
                await every_shelf.commit()
            except DBAPIError as exc:
                errors.append(exc)
                await every_shelf.rollback()

    assert errors == []
    db.expire_all()
    filed = await db.get(Item, record_id)
    assert filed is not None
    assert filed.quantity == 0
    assert filed.storage_location_id == place_id
