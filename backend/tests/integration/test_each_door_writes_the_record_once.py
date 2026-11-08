"""Every door that changes a record's number writes it once.

The record is the one number of a product on a shelf, and a door that wrote
it twice in one operation — the number, then the number again after the
bridge had moved the quant — left a moment in which the record and the
ledger told two stories, and gave a concurrent reader the chance to see the
first. The count is taken at the database: the statements that set
``items.quantity`` for the record while the door runs.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.testing import ModuleTestHelper, seed_org_storage_types
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.schemas.item import (
    ItemBulkUpdate,
    ItemConsumeRequest,
    ItemDiscardRequest,
    ItemQuantityUpdate,
    ItemUpdate,
)
from app.schemas.label_pool import LabelAssignRequest
from app.services.items._bulk_update import bulk_update_items
from app.services.items._lifecycle import delete_item, restore_item
from app.services.items._update import update_item, update_quantity
from app.services.items.move_service import consume_item, discard_item
from app.services.items.scan_service import assign_label_or_barcode
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@contextmanager
def _writes_of_the_number(db: AsyncSession) -> Iterator[list[str]]:
    """The statements *db* sends that write ``items.quantity`` while the block runs.

    Listened for on the session's own bind — an engine, or the connection a
    test harness pinned it to — rather than on every engine: a harness that
    opened its connection first is not reached by a class-wide listener.
    """
    seen: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        # A statement led by a comment naming who sent it is still the
        # statement that follows the comment.
        text = re.sub(r'^/\*.*?\*/', '', ' '.join(statement.split()), flags=re.S)
        text = text.strip().lower()
        if text.startswith('insert into items ') or (
            text.startswith('update items set')
            and 'quantity=' in text.split(' where ')[0]
        ):
            seen.append(text[:60])

    bind = db.sync_session.get_bind()
    event.listen(bind, 'before_cursor_execute', count)
    try:
        yield seen
    finally:
        event.remove(bind, 'before_cursor_execute', count)


async def _stocked(db: AsyncSession) -> tuple[Item, UserContextDTO]:
    org = Organization(
        name=f'Once {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(org)
    await db.flush()
    org_id = org.id
    await db.run_sync(lambda session: seed_org_storage_types(session, org_id))
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'once_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    person = UserContextDTO(id=user.id, organization_id=org.id)
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Aisle')
    product = ProductTemplate(
        organization_id=org.id, name='Rye', sku=f'RY-{uuid.uuid4().hex[:8]}'
    )
    db.add_all([shelf, product])
    await db.flush()
    record = await put_on_shelf(db, person, product, shelf.id, '10')
    await db.flush()
    return record, person


async def test_opening_a_record_writes_its_number_once(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    record, person = await _stocked(db)
    product = await db.get(ProductTemplate, record.template_id)
    assert product is not None

    with _writes_of_the_number(db) as writes:
        await put_on_shelf(db, person, product, record.storage_location_id, '4')
        await db.flush()

    assert len(writes) == 1, writes


_DOORS = {
    'quantity edit': lambda db, record, person: update_quantity(
        db, record, ItemQuantityUpdate(quantity=Decimal('7')), user_id=person.id
    ),
    'record edit': lambda db, record, person: update_item(
        db, record, ItemUpdate(quantity=Decimal('7')), person
    ),
    'bulk edit': lambda db, record, person: bulk_update_items(
        db,
        ItemBulkUpdate(item_ids=[record.id], update_data=ItemUpdate(quantity=7)),
        person,
    ),
    'consumption': lambda db, record, person: consume_item(
        db, record, ItemConsumeRequest(quantity=Decimal('3')), person
    ),
    'discard': lambda db, record, person: discard_item(
        db, record, ItemDiscardRequest(quantity=Decimal('3'), reason='damaged'), person
    ),
    'soft delete': lambda db, record, person: delete_item(db, record, person),
}


@pytest.mark.parametrize('door', list(_DOORS))
async def test_a_door_writes_the_number_once(
    real_async_db_session: AsyncSession, door: str
) -> None:
    db = real_async_db_session
    record, person = await _stocked(db)

    with _writes_of_the_number(db) as writes:
        await _DOORS[door](db, record, person)
        await db.flush()

    assert len(writes) == 1, writes


async def test_a_restore_writes_the_number_once(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    record, person = await _stocked(db)
    await delete_item(db, record, person)
    await db.flush()

    with _writes_of_the_number(db) as writes:
        await restore_item(db, record, person)
        await db.flush()

    assert len(writes) == 1, writes


async def test_a_rescan_writes_the_number_once(
    real_async_db_session: AsyncSession, async_test_user
) -> None:
    """The scan door: a second scan of a code bumps the existing record once."""
    db = real_async_db_session
    shelf = StorageLocation(
        organization_id=async_test_user.organization_id,
        created_by=async_test_user.id,
        name='Scan shelf',
        usage=LocationUsage.INTERNAL,
    )
    db.add(shelf)
    await db.flush()
    code = f'76{uuid.uuid4().int % 10**11:011d}'
    request = LabelAssignRequest(location_id=shelf.id, name='Kawa mielona', quantity=1)
    first = await assign_label_or_barcode(db, code, request, async_test_user)
    await db.flush()

    with _writes_of_the_number(db) as writes:
        second = await assign_label_or_barcode(db, code, request, async_test_user)
        await db.flush()

    assert second.id == first.id
    assert len(writes) == 1, writes
