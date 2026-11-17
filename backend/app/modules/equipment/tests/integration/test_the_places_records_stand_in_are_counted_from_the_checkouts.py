"""The places records are checked out to are counted from the checkouts.

A record checked out to a place names that place as well as its home, and
the delete guard counts both. The home half is one pass over the records.
The placement half used to ask, for every record of the organization,
whether a module had put it somewhere — a subquery correlated with the
record, evaluated once per row, whether or not the organization had a single
checkout. At a hundred thousand records that was ~150 ms on every narrowed
locations listing and every delete.

Driven from the placements instead — the open checkouts joined to the
records they name — the work follows the number of checkouts, not the number
of records. What is measured is the shape of the plan, not a clock: no
node of it is a per-record subplan.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.service import get_error_message
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.equipment.models import EquipmentAssignment
from app.services.auth_service import get_password_hash
from app.services.storage._queries import item_counts_naming_locations_async

pytestmark = pytest.mark.integration


async def _seed(db: AsyncSession) -> tuple[UUID, UUID, UUID]:
    org = Organization(
        name=f'Placed {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'equipment'],
    )
    db.add(org)
    await db.flush()
    user = User(
        email=f'placed_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Placed',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.flush()
    home = StorageLocation(name='Home', organization_id=org.id, created_by=user.id)
    desk = StorageLocation(name='Desk', organization_id=org.id, created_by=user.id)
    db.add_all([home, desk])
    await db.flush()
    records = [
        Item(
            name=f'Asset {n}',
            organization_id=org.id,
            storage_location_id=home.id,
            quantity=1,
        )
        for n in range(4)
    ]
    db.add_all(records)
    await db.flush()
    # One record checked out to the desk, one checked out to its own home,
    # one whose checkout was closed: only the first names a second place.
    now_out = {'checked_out_by': user.id, 'assigned_to_name': 'Someone'}
    db.add_all(
        [
            EquipmentAssignment(
                organization_id=org.id,
                item_id=records[0].id,
                checkout_location_id=desk.id,
                **now_out,
            ),
            EquipmentAssignment(
                organization_id=org.id,
                item_id=records[1].id,
                checkout_location_id=home.id,
                **now_out,
            ),
        ]
    )
    closed = EquipmentAssignment(
        organization_id=org.id,
        item_id=records[2].id,
        checkout_location_id=desk.id,
        **now_out,
    )
    closed.checked_in_at = datetime.now(UTC)
    db.add(closed)
    await db.flush()
    return org.id, home.id, desk.id


def _nodes(plan: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield plan
    for child in plan.get('Plans', ()):
        yield from _nodes(child)


async def test_the_counts_are_the_homes_plus_the_places_of_open_checkouts(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org_id, home_id, desk_id = await _seed(db)

    counts = await item_counts_naming_locations_async(db, org_id, [home_id, desk_id])

    # Four records live at home, one of them also named by the desk; the
    # record checked out to its own home is counted once, the closed
    # checkout names nothing.
    assert counts == {home_id: 4, desk_id: 1}


async def test_the_placement_half_is_not_a_subplan_per_record(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org_id, home_id, desk_id = await _seed(db)
    emitted: list[tuple[str, Any]] = []

    def _capture(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if 'equipment_assignments' in statement:
            emitted.append((statement, parameters))

    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', _capture)
    try:
        await item_counts_naming_locations_async(db, org_id, [home_id, desk_id])
    finally:
        event.remove(engine, 'before_cursor_execute', _capture)
    assert len(emitted) == 1, emitted

    statement, parameters = emitted[0]
    result = await db.run_sync(
        lambda session: session.connection().exec_driver_sql(
            f'EXPLAIN (FORMAT JSON) {statement}', parameters
        )
    )
    (planned,) = result.one()
    document = planned if isinstance(planned, list) else json.loads(planned)
    subplans = [
        node
        for node in _nodes(document[0]['Plan'])
        if node.get('Parent Relationship') == 'SubPlan'
    ]
    assert not subplans, document


def test_the_refusal_says_a_checkout_is_what_holds_the_place() -> None:
    # A place refused only because a record is checked out to it shows no
    # record on the general Locations screen, so the refusal has to name the
    # checkout instead of promising items nobody can see.
    assert 'checked out' in get_error_message('storage_delete_failed_items', 'en')
