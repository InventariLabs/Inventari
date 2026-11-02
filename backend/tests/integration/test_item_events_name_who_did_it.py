"""Every item event names who did it, in one key.

``item.used`` and ``item.disposed`` carried ``data.user_id``; ``item.updated``
carried ``data.user`` — null for a move — and ``item.moved`` carried no actor
at all. A receiver that audits or routes by person had to learn a shape per
event and then found two of them empty. The contract is one key, ``user_id``,
on every item event; the acting account's id when there is one, null when a
system path acted on nobody's behalf.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import SystemEvent
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemMove, ItemQuantityUpdate
from app.services.items import delete_item, move_item, restore_item, update_quantity
from tests.integration._core_api_helpers import make_user_context
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

BUS = 'app.core.events.event_bus.emit_transactional'


async def _record(db: AsyncSession, org_id, user, shelf_id) -> Item:
    template = ProductTemplate(
        organization_id=org_id, name='Bananas', sku=f'BAN-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    return await put_on_shelf(db, user, template, shelf_id, 3)


def _emitted(bus: AsyncMock) -> dict[str, Any]:
    """The payload of each event the call emitted, by wire name."""
    return {
        (event.value if isinstance(event, SystemEvent) else str(event)): payload
        for _db, event, payload in (call.args for call in bus.await_args_list)
    }


async def test_a_move_names_who_moved_in_both_its_events(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    db = real_async_db_session
    record = await _record(
        db, async_test_household.id, async_test_user, async_test_storage_location.id
    )
    shelf = StorageLocation(
        organization_id=async_test_household.id,
        name='Other shelf',
        created_by=async_test_storage_location.created_by,
    )
    db.add(shelf)
    await db.flush()

    with patch(BUS, new_callable=AsyncMock) as bus:
        await move_item(
            db,
            record,
            ItemMove(to_location_id=shelf.id),
            user=make_user_context(record.organization_id, async_test_user.id),
        )

    events = _emitted(bus)
    assert events['item.updated'].user_id == str(async_test_user.id)
    assert events['item.moved'].user_id == str(async_test_user.id)


async def test_a_delete_and_a_restore_name_who_did_them(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    db = real_async_db_session
    record = await _record(
        db, async_test_household.id, async_test_user, async_test_storage_location.id
    )
    user = make_user_context(record.organization_id, async_test_user.id)

    with patch(BUS, new_callable=AsyncMock) as bus:
        await delete_item(db, record, user)
    assert _emitted(bus)['item.deleted'].user_id == str(async_test_user.id)

    with patch(BUS, new_callable=AsyncMock) as bus:
        await restore_item(db, record, user)
    assert _emitted(bus)['item.updated'].user_id == str(async_test_user.id)


async def test_a_quantity_edit_names_who_made_it_and_a_system_one_names_nobody(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    db = real_async_db_session
    record = await _record(
        db, async_test_household.id, async_test_user, async_test_storage_location.id
    )

    with patch(BUS, new_callable=AsyncMock) as bus:
        await update_quantity(
            db, record, ItemQuantityUpdate(quantity=5), user_id=async_test_user.id
        )
    assert _emitted(bus)['item.updated'].user_id == str(async_test_user.id)

    with patch(BUS, new_callable=AsyncMock) as bus:
        await update_quantity(db, record, ItemQuantityUpdate(quantity=6))
    # The key is there, and null: an absent key reads as "this event never says".
    payload = _emitted(bus)['item.updated']
    assert 'user_id' in payload.model_dump()
    assert payload.user_id is None
