"""Two moves of one product in opposite directions finish together.

A move takes the goods off one shelf and puts them on the other, and each
half used to lock the quant it wrote as it got there. Moving flour from A to
B while someone moved flour from B to A therefore locked A in one
transaction and B in the other, and then each asked for the shelf the other
held: the database broke the circle by aborting one of them, and a person got
an error for a move nothing was wrong with.

Every group a move will write is now locked before the first write — its
anchor, in one order shared by every operation that locks more than one. The
second move waits for the first instead of meeting it halfway.

Each move here is held at the point where the movement pass is about to
write its records, until the other has arrived there too, or for two
seconds — the interleaving that closed the circle. With the locks taken up
front the second move never arrives: it is waiting for the first to finish,
which is what the two seconds are for.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.contracts import RecordPostDTO
from app.core.public_api import core_api
from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemMove
from app.services import _stock_quant_ops
from app.services.items import move_item

from ._core_api_helpers import make_template, make_user_context
from ._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Which of the two transactions the running task is.
_WHO: contextvars.ContextVar[str] = contextvars.ContextVar('who')


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _Meeting:
    """Each side waits at the meeting point for the other, for a while."""

    def __init__(self) -> None:
        self.arrived = {'there': asyncio.Event(), 'back': asyncio.Event()}

    async def meet(self) -> None:
        me = _WHO.get(None)
        if me is None or self.arrived[me].is_set():
            return
        self.arrived[me].set()
        other = 'back' if me == 'there' else 'there'
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.arrived[other].wait(), timeout=2)


async def _move_with(
    db: AsyncSession, org_id, template_id, source, target, user_id
) -> None:
    # A module moving one unit states the two records it changes. It reads
    # their numbers under the groups' locks, as a door must, and the pass
    # writes them inside the same locks, beside the movement.
    await core_api.stock.lock_async(
        db, org_id, keys=[(template_id, source), (template_id, target)]
    )
    records = {
        record.storage_location_id: record
        for record in (
            await db.scalars(
                select(Item).where(
                    Item.template_id == template_id,
                    Item.is_deleted.is_(False),
                )
            )
        ).all()
    }
    await core_api.stock.post_movement_async(
        db,
        org_id,
        template_id,
        Decimal('1'),
        from_location_id=source,
        to_location_id=target,
        reference_type='item',
        reference_id=uuid.uuid4(),
        created_by=user_id,
        records=[
            RecordPostDTO(
                item_id=records[source].id,
                new_quantity=records[source].quantity - 1,
            ),
            RecordPostDTO(
                item_id=records[target].id,
                new_quantity=records[target].quantity + 1,
            ),
        ],
    )


async def _relocate_with(
    db: AsyncSession, org_id, template_id, source, target, user_id
) -> None:
    # The record standing on *source*, carried through the move door: the
    # door locks both shelves before it writes the record's shelf.
    record = (
        await db.scalars(
            select(Item).where(
                Item.template_id == template_id,
                Item.storage_location_id == source,
                Item.is_deleted.is_(False),
            )
        )
    ).one()
    await move_item(
        db,
        record,
        ItemMove(to_location_id=target),
        user=make_user_context(org_id, user_id),
    )


@pytest.mark.parametrize(
    'move',
    [_move_with, _relocate_with],
    ids=['a movement posted by a module', 'a record carried to another shelf'],
)
async def test_moves_there_and_back_both_finish(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
    monkeypatch: pytest.MonkeyPatch,
    move: Callable[..., Awaitable[None]],
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    shelf_a = async_test_storage_location.id
    other = StorageLocation(
        organization_id=org_id,
        created_by=async_test_storage_location.created_by,
        name='Shelf B',
    )
    db.add(other)
    await db.flush()
    shelf_b = other.id
    template = await db.run_sync(lambda s: make_template(s, org_id, name='Flour'))
    for shelf in (shelf_a, shelf_b):
        await put_on_shelf(db, async_test_user, template, shelf, 10)
    await db.commit()

    meeting = _Meeting()
    write_the_records = _stock_quant_ops._write_the_records

    async def meet_then_write_the_records(*args, **kwargs):
        await meeting.meet()
        return await write_the_records(*args, **kwargs)

    monkeypatch.setattr(
        _stock_quant_ops, '_write_the_records', meet_then_write_the_records
    )

    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def one_way(name: str, source, target) -> None:
        _WHO.set(name)
        async with factory() as session:
            await move(session, org_id, template.id, source, target, async_test_user.id)
            await session.commit()

    try:
        outcomes = await asyncio.gather(
            one_way('there', shelf_a, shelf_b),
            one_way('back', shelf_b, shelf_a),
            return_exceptions=True,
        )
    finally:
        await engine.dispose()

    assert outcomes == [None, None], outcomes
    shelves = {
        row.storage_location_id: row.quantity
        for row in (
            await db.scalars(
                select(ShelfRow).where(ShelfRow.product_template_id == template.id)
            )
        ).all()
    }
    assert shelves == {shelf_a: Decimal('10'), shelf_b: Decimal('10')}
