"""A location is read with what hangs from it and what it hangs from, not with the tree.

A stock take looked its location up in the organization's first 2 000
locations and searched that list for the subtree and the ancestors it needs,
so a location past the 2 000th answered "not found" for a shelf that existed.
The subtree and the chain above are two recursive statements, and their cost
follows the size of the subtree and the depth of the tree.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@contextmanager
def _statements(db: AsyncSession) -> Iterator[list[str]]:
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        seen.append(' '.join(statement.split()).lower())

    bind = db.sync_session.get_bind()
    event.listen(bind, 'before_cursor_execute', record)
    try:
        yield seen
    finally:
        event.remove(bind, 'before_cursor_execute', record)


async def _organization(db: AsyncSession, name: str) -> tuple[Organization, Any]:
    org = Organization(name=f'{name} {uuid.uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'{name}_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    return org, user


async def _place(
    db: AsyncSession,
    org: Organization,
    user: Any,
    name: str,
    parent: StorageLocation | None = None,
    *,
    archived: bool = False,
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org.id,
        created_by=user.id,
        name=name,
        parent_id=parent.id if parent else None,
        settings={'archived': True} if archived else {},
    )
    db.add(location)
    await db.flush()
    return location


async def test_the_subtree_starts_with_the_location_and_the_ancestors_run_nearest_first(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org, user = await _organization(db, 'tree')
    warehouse = await _place(db, org, user, 'Warehouse')
    zone = await _place(db, org, user, 'Zone', warehouse)
    rack = await _place(db, org, user, 'Rack', zone)
    shelf = await _place(db, org, user, 'Shelf', rack)
    await _place(db, org, user, 'Sibling rack', zone)

    subtree, ancestors = await core_api.locations.subtree_and_ancestors_async(
        db, org.id, rack.id
    )

    assert [s.id for s in subtree][0] == rack.id
    assert {s.id for s in subtree} == {rack.id, shelf.id}
    assert [a.id for a in ancestors] == [zone.id, warehouse.id]


async def test_a_location_of_another_organization_is_not_found(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org, user = await _organization(db, 'mine')
    other, other_user = await _organization(db, 'theirs')
    foreign = await _place(db, other, other_user, 'Foreign shelf')

    assert await core_api.locations.subtree_and_ancestors_async(
        db, org.id, foreign.id
    ) == ([], [])


async def test_an_archived_location_hides_what_hangs_from_it_and_ends_the_chain(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org, user = await _organization(db, 'archive')
    warehouse = await _place(db, org, user, 'Warehouse')
    old_zone = await _place(db, org, user, 'Old zone', warehouse, archived=True)
    shelf = await _place(db, org, user, 'Shelf', old_zone)
    live_zone = await _place(db, org, user, 'Live zone', warehouse)
    live_shelf = await _place(db, org, user, 'Live shelf', live_zone)

    archived = await core_api.locations.subtree_and_ancestors_async(
        db, org.id, old_zone.id
    )
    below_archived = await core_api.locations.subtree_and_ancestors_async(
        db, org.id, shelf.id
    )
    around_live = await core_api.locations.subtree_and_ancestors_async(
        db, org.id, warehouse.id
    )

    assert archived == ([], [])
    # The shelf itself is listed; the archived zone above it ends the chain.
    assert [s.id for s in below_archived[0]] == [shelf.id]
    assert below_archived[1] == []
    assert {s.id for s in around_live[0]} == {warehouse.id, live_zone.id, live_shelf.id}


async def test_the_cost_follows_the_subtree_and_not_the_organization(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org, user = await _organization(db, 'many')
    rack = await _place(db, org, user, 'Rack')
    shelf = await _place(db, org, user, 'Shelf', rack)
    db.add_all(
        StorageLocation(organization_id=org.id, created_by=user.id, name=f'Other {n}')
        for n in range(300)
    )
    await db.flush()

    with _statements(db) as seen:
        subtree, ancestors = await core_api.locations.subtree_and_ancestors_async(
            db, org.id, shelf.id
        )

    assert [s.id for s in subtree] == [shelf.id]
    assert [a.id for a in ancestors] == [rack.id]
    assert len(seen) == 2


async def test_locations_named_by_id_come_back_by_name_without_the_archived(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org, user = await _organization(db, 'named')
    other, other_user = await _organization(db, 'foreign')
    zebra = await _place(db, org, user, 'Zebra shelf')
    apple = await _place(db, org, user, 'Apple shelf')
    gone = await _place(db, org, user, 'Gone shelf', archived=True)
    foreign = await _place(db, other, other_user, 'Foreign shelf')

    named = await core_api.locations.list_by_ids_async(
        db, org.id, [zebra.id, apple.id, gone.id, foreign.id, uuid.uuid4()]
    )

    assert [s.id for s in named] == [apple.id, zebra.id]


async def test_a_stock_take_finds_a_location_past_the_two_thousandth(
    real_async_db_session: AsyncSession,
) -> None:
    from app.modules.stock_takes.storage_lookup_service import get_storage_tree

    db = real_async_db_session
    org, user = await _organization(db, 'past')
    db.add_all(
        StorageLocation(organization_id=org.id, created_by=user.id, name=f'A_{n:05d}')
        for n in range(2100)
    )
    last = await _place(db, org, user, 'Z_created after the seed')
    child = await _place(db, org, user, 'Z_child', last)

    snapshot_ids, family_ids, paths = await get_storage_tree(db, org.id, last.id)

    assert set(snapshot_ids) == {last.id, child.id}
    assert set(family_ids) == {last.id, child.id}
    assert paths[child.id] == 'Z_created after the seed / Z_child'
