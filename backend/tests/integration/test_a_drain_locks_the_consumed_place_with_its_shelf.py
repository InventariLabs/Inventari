"""A draw that empties a record takes the Consumed place's lock with its shelf's.

Taking the last unit of a record files it under the organization's Consumed
place, a group of the same product with an anchor of its own. An operation
that locks every shelf of the product takes the anchors in ``id`` order, so
it may take the Consumed place's before the shelf's. A draw that took the
shelf first and named the Consumed place only when it filed the record
therefore met that operation half way: each held what the other waited for,
and the database aborted one of them with a deadlock.

Here the Consumed place's anchor has the lower ``id``, the draw is stopped
between taking its shelf and filing the record, and the other operation
queues behind it. Whatever the draw held by then, both must go through.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.public_api import core_api
from app.models.item import Item
from app.models.stock_anchor import StockAnchor
from app.models.storage_location import LocationUsage
from app.services._stock_quant_ops import take_from_the_records_async
from app.services.items import _consumed_place
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


async def test_a_draw_that_files_a_record_and_a_lock_of_every_shelf_do_not_deadlock(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    engine: AsyncEngine,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    home = async_test_storage_location.id
    template = await db.run_sync(
        lambda s: make_template(s, org_id, name=f'Rice {uuid.uuid4().hex[:6]}')
    )
    keeper = await shelf_keeper(db, org_id)
    template_id = template.id
    await ensure_virtual_locations_async(db, str(org_id), str(keeper.id))
    consumed = await get_virtual_location_async(db, str(org_id), LocationUsage.CUSTOMER)
    assert consumed is not None
    consumed_id = consumed.id
    # The anchors are given their ids here so the order the lock takes them
    # in does not depend on which uuid the database happened to draw.
    for anchor_id, shelf in (
        (uuid.UUID(int=1), consumed_id),
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
    record_id = (await put_on_shelf(db, keeper, template, home, 5)).id
    await db.commit()

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
        with patch.object(
            _consumed_place, 'lock_shelf_change_async', stopped_before_the_filing
        ):
            draw = asyncio.create_task(
                take_from_the_records_async(
                    drain,
                    org_id,
                    template_id,
                    home,
                    Decimal('5'),
                    user_id=keeper.id,
                    file_when_emptied=True,
                )
            )
            await asyncio.wait_for(reached_the_filing.wait(), _NEVER_ARRIVES_AFTER)
            other_pid = await _pid(every_shelf)
            other = asyncio.create_task(
                core_api.stock.lock_async(
                    every_shelf, org_id, keys=[(template_id, None)]
                )
            )
            await _waiting_on(engine, other_pid, other)
            carry_on.set()
            try:
                await asyncio.wait_for(draw, _NEVER_ARRIVES_AFTER)
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
    record = await db.get(Item, record_id)
    assert record is not None
    assert record.quantity == 0
    assert record.storage_location_id == consumed_id
