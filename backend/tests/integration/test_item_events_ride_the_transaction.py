"""An item event leaves with the write that caused it, not after it.

The items services used to announce a change with a plain ``emit`` -- an XADD
the moment the line ran. Two windows followed from that: a rollback after the
emit announced something that never happened (and the webhook went out
anyway), and a crash between the commit and the XADD changed the data and told
nobody. The events now go through ``emit_transactional``: a row in the outbox
in the caller's transaction, relayed after the commit.

Outside TESTING the outbox row is the whole mechanism, so these tests switch
TESTING off around the write and read the row back.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core._event_bus import EventBus
from app.core.contracts import UserContextDTO
from app.core.outbox_relay import relay_outbox_batch
from app.models.event_outbox import EventOutbox
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.schemas.item import (
    ItemConsumeRequest,
    ItemMove,
    ItemQuantityUpdate,
    ItemUpdate,
)
from app.schemas.label_pool import LabelAssignRequest
from app.services.items import (
    delete_item,
    move_item,
    purge_item,
    restore_item,
    update_item,
    update_quantity,
)
from app.services.items.move_service import consume_item
from app.services.items.scan_service import assign_label_or_barcode
from tests.integration._core_api_helpers import make_user_context
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class Scene:
    """One record on a shelf, a second shelf, and the user acting on them."""

    def __init__(
        self,
        db: AsyncSession,
        record: Item,
        shelf: StorageLocation,
        user: UserContextDTO,
        template: ProductTemplate,
        keeper: Any,
    ) -> None:
        self.db = db
        self.record = record
        self.shelf = shelf
        self.user = user
        self.template = template
        self.keeper = keeper
        self.code = ''


@pytest.fixture
async def scene(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> Scene:
    db = real_async_db_session
    org_id = async_test_household.id
    template = ProductTemplate(
        organization_id=org_id, name='Bananas', sku=f'BAN-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    shelf = StorageLocation(
        organization_id=org_id,
        name='Other shelf',
        created_by=async_test_storage_location.created_by,
    )
    db.add(shelf)
    await db.flush()
    record = await put_on_shelf(
        db, async_test_user, template, async_test_storage_location.id, 5
    )
    # Setup runs under TESTING, which buffers instead of writing the outbox;
    # the buffer is not what these tests are about.
    db.info.pop('_pending_outbox_events', None)
    await db.commit()
    return Scene(
        db,
        record,
        shelf,
        make_user_context(org_id, async_test_user.id),
        template,
        async_test_user,
    )


async def _deleted(s: Scene) -> None:
    await delete_item(s.db, s.record, s.user)
    s.db.info.pop('_pending_outbox_events', None)
    await s.db.commit()


def _scan_request(s: Scene) -> LabelAssignRequest:
    return LabelAssignRequest(location_id=s.shelf.id, name='Kawa mielona', quantity=1)


async def _scanned_once(s: Scene) -> None:
    s.code = f'76{uuid.uuid4().int % 10**11:011d}'
    await assign_label_or_barcode(s.db, s.code, _scan_request(s), s.keeper)
    s.db.info.pop('_pending_outbox_events', None)
    await s.db.commit()


async def _rescan(s: Scene) -> None:
    await assign_label_or_barcode(s.db, s.code, _scan_request(s), s.keeper)


async def _create(s: Scene) -> None:
    await put_on_shelf(s.db, s.keeper, s.template, s.shelf.id, 2)


# (what the write is, what it does first without being under test, the write,
# the events it announces in the order they were emitted)
Case = tuple[
    Callable[[Scene], Awaitable[None]] | None,
    Callable[[Scene], Awaitable[Any]],
    list[str],
]

CASES: dict[str, Case] = {
    'create': (None, _create, ['item.created']),
    'edit': (
        None,
        lambda s: update_item(s.db, s.record, ItemUpdate(name='Renamed'), s.keeper),
        ['item.updated'],
    ),
    'quantity': (
        None,
        lambda s: update_quantity(
            s.db, s.record, ItemQuantityUpdate(quantity=9), user_id=s.keeper.id
        ),
        ['item.updated'],
    ),
    'move': (
        None,
        lambda s: move_item(
            s.db, s.record, ItemMove(to_location_id=s.shelf.id), s.user
        ),
        ['item.updated', 'item.moved'],
    ),
    'consume': (
        None,
        lambda s: consume_item(
            s.db, s.record, ItemConsumeRequest(quantity=Decimal('1')), s.user
        ),
        ['item.used'],
    ),
    'delete': (None, lambda s: delete_item(s.db, s.record, s.user), ['item.deleted']),
    'restore': (
        _deleted,
        lambda s: restore_item(s.db, s.record, s.user),
        ['item.updated'],
    ),
    'purge': (
        _deleted,
        lambda s: purge_item(s.db, s.record, s.user, reason='test'),
        ['item.deleted'],
    ),
    'rescan': (_scanned_once, _rescan, ['item.updated']),
}


async def _outbox(db: AsyncSession, org_id: uuid.UUID) -> list[EventOutbox]:
    rows = await db.scalars(
        select(EventOutbox)
        .where(EventOutbox.organization_id == org_id)
        .order_by(EventOutbox.created_at)
    )
    return list(rows.all())


@pytest.fixture(autouse=True)
async def _clean_outbox(real_async_db_session: AsyncSession):
    await real_async_db_session.execute(delete(EventOutbox))
    await real_async_db_session.commit()
    yield


@pytest.mark.parametrize('case', CASES)
async def test_a_rollback_after_the_write_announces_nothing(
    scene: Scene, case: str
) -> None:
    before, write, _ = CASES[case]
    if before:
        await before(scene)
    org_id = scene.user.organization_id

    with (
        patch.object(settings, 'TESTING', False),
        patch.object(EventBus, 'emit', new_callable=AsyncMock) as plain_emit,
    ):
        await write(scene)
        await scene.db.rollback()

    assert await _outbox(scene.db, org_id) == []
    # The teeth: a plain emit is a message sent the moment the line runs, and
    # nothing a rollback does takes it back.
    plain_emit.assert_not_awaited()


@pytest.mark.parametrize('case', CASES)
async def test_a_commit_announces_each_event_once_in_the_order_it_was_emitted(
    scene: Scene, case: str
) -> None:
    before, write, expected = CASES[case]
    if before:
        await before(scene)
    org_id = scene.user.organization_id

    with patch.object(settings, 'TESTING', False):
        await write(scene)
        await scene.db.commit()

    rows = await _outbox(scene.db, org_id)
    assert [row.event for row in rows] == expected
    assert all(row.published_at is None for row in rows)
    # The relay reads by this column. One instant for every row of a
    # transaction (what ``now()`` gives) leaves the order of a move's two
    # events to the planner.
    stamps = [row.created_at for row in rows]
    assert all(a < b for a, b in zip(stamps, stamps[1:], strict=False))

    # What the relay sends is what the webhook module receives: the same
    # events, once, in the order of the writes that made them.
    bus = EventBus()
    bus._stream_name = f'item_events_stream_{uuid.uuid4().hex[:12]}'
    bus._group_name = f'item_events_group_{uuid.uuid4().hex[:12]}'
    await bus.connect(settings.REDIS_URL)
    assert bus._redis is not None, 'test requires a reachable Redis'
    try:
        with patch('app.core.outbox_relay.event_bus', bus):
            await relay_outbox_batch(scene.db)
        messages = await bus._redis.xrange(bus._stream_name)
        assert [data['event'] for _, data in messages] == expected
    finally:
        await bus._redis.delete(bus._stream_name)
        await bus.disconnect()
