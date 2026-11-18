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

The mirror predicate, "the category is one this module claims", had the same
shape on the module-scoped path — the equipment locations page's count — and
got the same plan: the planner walked the warehouse record by record to find
the module's few. It now reads the claimed categories once and names them in
the statement, so the count reads the records rather than weighing every one
of them. A module's records are a minority spread through the warehouse, so
there the assertion is the shape of the read — an Index Scan hands the heap
back one record at a time, a bitmap or a sequential scan reads its pages
once — and not the number of blocks, which both plans touch when every page
holds a record of the module.

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
        self.claimed_expected: dict[UUID, int]


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
    fixture.claimed_expected = {}
    for n in range(1, _RECORDS + 1):
        shelf = fixture.shelf_ids[(n * 7919) % shelf_count]
        if n % _CLAIMED_EVERY in (0, 1):
            fixture.claimed_expected[shelf] = fixture.claimed_expected.get(shelf, 0) + 1
        else:
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
    db: AsyncSession, warehouse: _Warehouse, *, module_scope: str | None = None
) -> tuple[dict[UUID, int], tuple[str, Any]]:
    """The screens' count of every place, and the statement it ran.

    Without *module_scope* it is the general screens' count, narrowed the way
    ``GET /items`` narrows; with one, the module's own screen's count.
    """
    emitted: list[tuple[str, Any]] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if 'FROM items' in statement and 'count(' in statement:
            emitted.append((statement, parameters))

    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', _capture)
    try:
        if module_scope is None:
            counts = await item_counts_by_location_async(
                db,
                warehouse.org_id,
                warehouse.location_ids,
                claimed_tags={'equipment'},
            )
        else:
            counts = await item_counts_by_location_async(
                db,
                warehouse.org_id,
                warehouse.location_ids,
                module_scope=module_scope,
            )
    finally:
        event.remove(engine, 'before_cursor_execute', _capture)
    assert len(emitted) == 1, emitted
    return counts, emitted[0]


def _assert_read_in_table_order(plan: dict) -> None:
    """Every record read from a page of the table, not visited on its own."""
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


class TestTheWholeWarehouseIsCountedInOneRead:
    async def test_each_record_is_read_from_its_page_not_visited_on_its_own(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> None:
        db = real_async_db_session
        _, emitted = await _counted(db, warehouse)
        _assert_read_in_table_order(await _plan_of(db, *emitted))

    async def test_the_count_leaves_out_the_modules_records(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> None:
        counts, _ = await _counted(real_async_db_session, warehouse)
        assert counts == warehouse.expected


class TestTheModulesOwnRecordsAreCountedInOneRead:
    """The equipment locations page asks the same count, narrowed to its records.

    Its filter is the mirror of the general one — "is this record ours" — and
    does not ask the category question correlated with every record. The
    planner would price that per record and walk the warehouse through the
    organization index, visiting a record at a time; named as the values they
    are, the claimed categories let it read the records in the table's own
    order.
    """

    async def test_each_record_is_read_from_its_page_not_visited_on_its_own(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> None:
        db = real_async_db_session
        _, emitted = await _counted(db, warehouse, module_scope='equipment')
        plan = await _plan_of(db, *emitted)
        nodes = list(_nodes(plan))

        reads = [node for node in nodes if node.get('Relation Name') == 'items']
        assert reads, _shape(plan)
        # An Index Scan hands the heap back a record at a time. A count of
        # what a module keeps below a warehouse reads the pages once — in the
        # table's order, or through a bitmap of them.
        assert 'Index Scan' not in [node['Node Type'] for node in reads], _shape(plan)
        # The module's categories are values the count read once, not a table
        # read for every record it weighs.
        assert 'categories' not in {node.get('Relation Name') for node in nodes}, (
            _shape(plan)
        )

    async def test_the_count_names_only_the_modules_records(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> None:
        counts, _ = await _counted(
            real_async_db_session, warehouse, module_scope='equipment'
        )
        assert counts == warehouse.claimed_expected
