"""A location's count over a whole warehouse reads each record once.

A page of locations that holds the root of a warehouse, or the containers
above its shelves, counts every record below them; so do the first level of
the tree and the warehouse's own branch. The general screens count only what
their lists show, which leaves out a module's records — and the filter that
says so asked, for every record, whether its category was a module's.

The database answers that question with one hashed set either way. The
planner, though, priced the correlated form as one category lookup per
record, so the plain read of the organization's records looked expensive,
and it walked the records through the location index instead: one random
visit to the table per record, then a sort. At a hundred thousand products
that count cost more than three times what the same count cost without the
filter, and a list answer holding a warehouse root took twice as long as the
budget of its screen.

Asked as "the category is not one a module claims", the same records are
counted, and the planner prices the filter as the single set it is. What is
measured is the work the statement does — the blocks it touches in
``items`` for each record it reads — and not a clock: a clock measures the
machine.

The fixture is one warehouse of four zones and forty shelves, and two
neighbors on the same table, at a size where the per-record walk is the
plan the old filter got.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.services.storage._queries import item_counts_by_location_async

pytestmark = pytest.mark.integration

_ZONES = 4
_SHELVES_PER_ZONE = 10
_RECORDS = 12_000
_NEIGHBORS = 2
_NEIGHBOR_RECORDS = 6_000

#: Every tenth record is a module's: filed under its category, or under
#: none with the module's name on it. The rest are the organization's own.
_CLAIMED_EVERY = 10

_ITEMS_SQL = text(
    """
    INSERT INTO items (
        id, organization_id, storage_location_id, name, quantity,
        added_date, is_deleted, is_catalog_entry, created_at, updated_at,
        category_id, module_name
    )
    SELECT
        gen_random_uuid(), :org_id,
        (CAST(:shelves AS uuid[]))[1 + (n * 7919) % CAST(:shelf_count AS int)],
        'Record ' || n, 1, CURRENT_DATE, false, false, now(), now(),
        CASE
            WHEN n % CAST(:claimed_every AS int) = 0 THEN CAST(:claimed_category AS uuid)
            WHEN n % CAST(:claimed_every AS int) = 1 THEN NULL
            ELSE (CAST(:categories AS uuid[]))[1 + n % 3]
        END,
        CASE WHEN n % CAST(:claimed_every AS int) = 1 THEN 'equipment' END
    FROM generate_series(1, CAST(:count AS int)) AS n
    """
)


class _Warehouse:
    def __init__(self) -> None:
        self.org_id: UUID
        self.location_ids: list[UUID]
        self.shelf_ids: list[UUID]
        self.expected: dict[UUID, int]


async def _warehouse_of(
    db: AsyncSession, organization: Organization, records: int
) -> tuple[list[UUID], list[UUID]]:
    """Root, zones and shelves of one organization, *records* records on them."""
    user = await ModuleTestHelper.create_user_async(
        db, organization, email=f'count_{uuid4().hex[:8]}@test.com'
    )

    def place(name: str, parent: StorageLocation | None) -> StorageLocation:
        row = StorageLocation(
            name=f'{name} {uuid4().hex[:4]}',
            organization_id=organization.id,
            parent_id=parent.id if parent else None,
            usage='internal',
            created_by=user.id,
        )
        db.add(row)
        return row

    root = place('Warehouse', None)
    await db.flush()
    zones = [place(f'Zone {z}', root) for z in range(_ZONES)]
    await db.flush()
    shelves = [
        place(f'Shelf {z}.{s}', zone)
        for z, zone in enumerate(zones)
        for s in range(_SHELVES_PER_ZONE)
    ]
    await db.flush()

    ordinary = [
        Category(name=f'Goods {c}', organization_id=organization.id) for c in range(3)
    ]
    claimed = Category(
        name='Laptops', organization_id=organization.id, context_tag='equipment'
    )
    db.add_all([*ordinary, claimed])
    await db.flush()

    shelf_ids = [shelf.id for shelf in shelves]
    await db.execute(
        _ITEMS_SQL,
        {
            'org_id': organization.id,
            'shelves': [str(i) for i in shelf_ids],
            'shelf_count': len(shelf_ids),
            'claimed_every': _CLAIMED_EVERY,
            'claimed_category': claimed.id,
            'categories': [str(c.id) for c in ordinary],
            'count': records,
        },
    )
    location_ids = [root.id, *(zone.id for zone in zones), *shelf_ids]
    return location_ids, shelf_ids


@pytest.fixture
async def warehouse(real_async_db_session: AsyncSession) -> _Warehouse:
    db = real_async_db_session
    fixture = _Warehouse()
    reader = Organization(
        name=f'Counted {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    neighbors = [
        Organization(
            name=f'Count neighbor {n} {uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'locations'],
        )
        for n in range(_NEIGHBORS)
    ]
    db.add_all([reader, *neighbors])
    await db.commit()

    fixture.org_id = reader.id
    fixture.location_ids, fixture.shelf_ids = await _warehouse_of(db, reader, _RECORDS)
    for neighbor in neighbors:
        await _warehouse_of(db, neighbor, _NEIGHBOR_RECORDS)
    await db.commit()

    # What the general screens show on each shelf, counted by the fixture's
    # own rule rather than read back through the code under test.
    shelf_count = len(fixture.shelf_ids)
    fixture.expected = {}
    for n in range(1, _RECORDS + 1):
        if n % _CLAIMED_EVERY in (0, 1):
            continue
        shelf = fixture.shelf_ids[(n * 7919) % shelf_count]
        fixture.expected[shelf] = fixture.expected.get(shelf, 0) + 1

    # Left uncommitted on purpose, as in the items list's plan test: the
    # locks keep an autovacuum that began before the seed from replacing
    # these statistics before the read plans on them.
    await db.execute(text('ANALYZE items'))
    await db.execute(text('ANALYZE categories'))
    await db.execute(text('ANALYZE storage_locations'))
    return fixture


def _nodes(plan: dict) -> Iterator[dict]:
    yield plan
    for child in plan.get('Plans', ()):
        yield from _nodes(child)


def _shape(plan: dict) -> str:
    return ' -> '.join(
        node['Node Type']
        + (f' on {node["Relation Name"]}' if node.get('Relation Name') else '')
        + (f' [{node["Index Name"]}]' if node.get('Index Name') else '')
        for node in _nodes(plan)
    )


async def _plan_of(db: AsyncSession, statement: str, parameters: Any) -> dict:
    """The plan of the statement the count emitted, bind values and all."""
    result = await db.run_sync(
        lambda session: session.connection().exec_driver_sql(
            f'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}', parameters
        )
    )
    (planned,) = result.one()
    document = planned if isinstance(planned, list) else json.loads(planned)
    return document[0]['Plan']


async def _counted(
    db: AsyncSession, warehouse: _Warehouse
) -> tuple[dict[UUID, int], tuple[str, Any]]:
    """The general screens' count of every place, and the statement it ran."""
    emitted: list[tuple[str, Any]] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if 'FROM items' in statement and 'count(' in statement:
            emitted.append((statement, parameters))

    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', _capture)
    try:
        counts = await item_counts_by_location_async(
            db,
            warehouse.org_id,
            warehouse.location_ids,
            claimed_tags={'equipment'},
        )
    finally:
        event.remove(engine, 'before_cursor_execute', _capture)
    assert len(emitted) == 1, emitted
    return counts, emitted[0]


class TestTheWholeWarehouseIsCountedInOneRead:
    async def test_each_record_is_read_from_its_page_not_visited_on_its_own(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> None:
        db = real_async_db_session
        _, emitted = await _counted(db, warehouse)
        plan = await _plan_of(db, *emitted)

        reads = [node for node in _nodes(plan) if node.get('Relation Name') == 'items']
        assert reads, _shape(plan)
        # A parallel read reports its rows per worker and its blocks for all
        # of them together, so the rows are multiplied back by the loops.
        records = sum(
            (node['Actual Rows'] + node.get('Rows Removed by Filter', 0))
            * node['Actual Loops']
            for node in reads
        )
        blocks = sum(
            node['Shared Hit Blocks'] + node['Shared Read Blocks'] for node in reads
        )
        # A read in the table's own order touches a block for every page of
        # records — dozens of records each. The walk by location touched a
        # block for every record it counted.
        assert blocks * 4 < records, (blocks, records, _shape(plan))

    async def test_the_count_leaves_out_the_modules_records(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> None:
        counts, _ = await _counted(real_async_db_session, warehouse)
        assert counts == warehouse.expected
