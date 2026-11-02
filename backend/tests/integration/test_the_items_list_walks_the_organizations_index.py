"""The items list, walked in the organization's own index.

The list asks for one organization's records newest-first, a page at a time.
Scoped by storage location alone — which is how the user mode scoped it — the
organization is a property of the joined table, so the planner cannot answer
that order from ``ix_items_org_created``: it reads every record standing in
the organization's locations and sorts them in memory, on every page, and the
count the footer shows is taken the same way.

Naming the organization on the record changes no answer — the locations are
already that organization's own — and it is what lets the page be walked in
the index's order: the newest hundred records, then stop. The bill is paid per
page and grows with the warehouse, which is why the plan is the assertion here
and not the clock.

The plan is the real assertion. A sequential scan of ``items``, or a Sort node
above the read, means the page was assembled by reading and ordering the whole
slice. The page and the count are the backstops: a read that walks the index
but drops or duplicates rows still fails there.

The fixture seeds several thousand records for the reader and two standing
neighbors, so the index has to be worth choosing. The smallest seed at which
the planner takes ``ix_items_org_created`` over an in-memory sort was measured
at about a thousand records for the reader, with twice as many belonging to
other organizations, interleaved in write time; below that the whole slice
fits in a page of memory and sorting it is the cheaper answer. This file seeds
five thousand, well clear of the flip.

Note the measurement is of reads only. The development stack runs with
``fsync=off``, so the seeding time in this file means nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.services.items import get_items as get_items_service

pytestmark = pytest.mark.integration

#: One organization's warehouse, at the size where the choice of plan is
#: stable: four internal locations and several thousand records.
_READER_ITEMS = 5_000
_READER_LOCATIONS = 4

#: Two neighbors on the same table, each with the reader's own amount of
#: stock. Their records are what makes the plan honest: a table holding only
#: the reader's rows makes almost any index look perfect, which is not the
#: shape an instance has.
_BYSTANDERS = 2
_BYSTANDER_ITEMS = 5_000

#: The page the list opens with.
_PAGE = 100

_INDEX = 'ix_items_org_created'

_NAME = 'Widget'
_NEIGHBOR_NAME = 'Neighbor goods'

#: The moment the fixture counts back from, and the order the records are
#: written in: the newest record is ``seconds = 1``, so the first page is the
#: first hundred names — an expectation the fixture states rather than reads
#: back out of the table it just filled.
_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

#: A record is eleven numbers and dates, and the fixture needs thousands of
#: them: seeded row by row through the ORM, the fixture would cost more than
#: the read it exists to measure. The database writes its own rows instead,
#: and keeps the two rules the assertions lean on — a unique write time per
#: record, and a name that names its position.
_ITEMS_SQL = text(
    """
    INSERT INTO items (
        id, organization_id, storage_location_id, name, quantity,
        added_date, is_deleted, is_catalog_entry, created_at, updated_at,
        expiry_date
    )
    SELECT
        gen_random_uuid(), :org_id, :location_id, :prefix || n,
        (n * 137 % 50000)::numeric / 7,
        (CAST(:now AS timestamptz) - make_interval(days => n % 900))::date,
        false, false,
        CAST(:now AS timestamptz) - make_interval(secs => n * CAST(:second_step AS int)),
        CAST(:now AS timestamptz),
        CASE WHEN n % 3 = 0 THEN NULL
             ELSE (CAST(:now AS timestamptz)
                   + make_interval(days => n * 31 % 5000))::date END
    FROM generate_series(CAST(:first AS int), CAST(:last AS int)) AS n
    WHERE n % CAST(:locations AS int) = CAST(:remainder AS int)
    """
)


class _OrganizationStock:
    def __init__(self) -> None:
        self.org_id: UUID
        self.location_ids: list[UUID]
        self.item_count: int
        self.expected_names: list[str]


async def _seed_items(
    db: AsyncSession,
    *,
    org_id: UUID,
    location_ids: list[UUID],
    count: int,
    prefix: str,
    second_step: int,
) -> None:
    """Write *count* records of one organization, spread over its locations.

    One statement per location, each taking its share of the same series, so
    the records are interleaved across the shelves the way a warehouse fills
    them and no location is empty.
    """
    for index, location_id in enumerate(location_ids):
        await db.execute(
            _ITEMS_SQL,
            {
                'org_id': org_id,
                'location_id': location_id,
                'prefix': f'{prefix} ',
                'now': _NOW,
                'second_step': second_step,
                'first': 1,
                'last': count,
                'locations': len(location_ids),
                'remainder': index,
            },
        )


@pytest.fixture
async def organization_stock(
    real_async_db_session: AsyncSession,
) -> _OrganizationStock:
    """One organization's stock, and two neighbors standing beside it."""
    db = real_async_db_session
    fixture = _OrganizationStock()

    reader = Organization(
        name=f'Items list {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    neighbors = [
        Organization(
            name=f'Items neighbor {n} {uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'locations'],
        )
        for n in range(_BYSTANDERS)
    ]
    db.add(reader)
    db.add_all(neighbors)
    await db.commit()

    fixture.org_id = reader.id
    fixture.item_count = _READER_ITEMS
    fixture.location_ids = []

    for organization in [reader, *neighbors]:
        user = await ModuleTestHelper.create_user_async(
            db, organization, email=f'inv1976_{uuid4().hex[:8]}@test.com'
        )
        locations = [
            StorageLocation(
                name=f'Shelf {index} {uuid4().hex[:4]}',
                organization_id=organization.id,
                usage='internal',
                created_by=user.id,
            )
            for index in range(_READER_LOCATIONS)
        ]
        db.add_all(locations)
        await db.flush()

        if organization is reader:
            fixture.location_ids = [location.id for location in locations]
            await _seed_items(
                db,
                org_id=organization.id,
                location_ids=fixture.location_ids,
                count=_READER_ITEMS,
                prefix=_NAME,
                second_step=1,
            )
        else:
            # Interleaved in write time with the reader's own rows: a tenant's
            # records are not written in a block of their own on a shared
            # table, and the planner must see that shape.
            await _seed_items(
                db,
                org_id=organization.id,
                location_ids=[location.id for location in locations],
                count=_BYSTANDER_ITEMS,
                prefix=_NEIGHBOR_NAME,
                second_step=3,
            )

    await db.commit()

    # Planning off stale statistics is planning off a table Postgres thinks is
    # empty, which chooses a sequential scan whatever indexes exist.
    # The ANALYZE is deliberately left uncommitted: it holds the tables' locks
    # until teardown, so an autovacuum that began before the seed landed —
    # carrying an empty picture of a table — cannot replace these statistics
    # between here and the read that plans on them.
    await db.execute(text('ANALYZE items'))
    await db.execute(text('ANALYZE storage_locations'))

    fixture.expected_names = [f'{_NAME} {n}' for n in range(1, _PAGE + 1)]
    return fixture


async def _first_page(
    db: AsyncSession, fixture: _OrganizationStock
) -> tuple[list[Any], int]:
    """The first page, through the service the endpoint runs.

    ``sort_order='desc'`` is the direction the list opens with — the
    endpoint's own default, which the service does not assume.
    """
    return await db.run_sync(
        lambda session: get_items_service(
            db=session,
            user_storage_ids=list(fixture.location_ids),
            user_organization_id=fixture.org_id,
            limit=_PAGE,
            sort_order='desc',
        )
    )


def _nodes(plan: dict) -> Iterator[dict]:
    yield plan
    for child in plan.get('Plans', ()):
        yield from _nodes(child)


def _shape(plan: dict) -> str:
    """The plan as a line: what ran, and which index served each read.

    The plan itself is a document of hundreds of fields; what went wrong is
    always the nodes and the indexes, and a failure that prints all of it
    prints none of it.
    """
    return ' -> '.join(
        node['Node Type']
        + (f' on {node["Relation Name"]}' if node.get('Relation Name') else '')
        + (f' [{node["Index Name"]}]' if node.get('Index Name') else '')
        for node in _nodes(plan)
    )


async def _plan_of(db: AsyncSession, statement: str, parameters: Any) -> dict:
    """The plan of the statement the service emitted, bind values and all.

    The parameters go to the driver unchanged, as the service sent them, so
    what is explained is the query that ran rather than a copy of it that
    could drift from it.
    """
    result = await db.run_sync(
        lambda session: session.connection().exec_driver_sql(
            f'EXPLAIN (ANALYZE, FORMAT JSON) {statement}', parameters
        )
    )
    (planned,) = result.one()
    # asyncpg hands the JSON column back decoded; a driver that returns the
    # text leaves the parsing here.
    document = planned if isinstance(planned, list) else json.loads(planned)
    return document[0]['Plan']


class TestThePageIsWalkedInTheIndexOrder:
    async def test_the_plan_does_not_sort_the_organization(
        self,
        real_async_db_session: AsyncSession,
        organization_stock: _OrganizationStock,
    ) -> None:
        db = real_async_db_session
        emitted: list[tuple[str, Any]] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            if 'FROM items' in statement and 'ORDER BY' in statement:
                emitted.append((statement, parameters))

        engine = db.get_bind()
        event.listen(engine, 'before_cursor_execute', _capture)
        try:
            await _first_page(db, organization_stock)
        finally:
            event.remove(engine, 'before_cursor_execute', _capture)

        # The count the server takes beside the page reads no order of its own.
        assert len(emitted) == 1, emitted
        plan = await _plan_of(db, *emitted[0])

        nodes = list(_nodes(plan))
        reads = [node for node in nodes if node.get('Relation Name') == 'items']
        assert reads, _shape(plan)

        # The ordering is the index's own order, so a Sort node would mean the
        # database read every record of the organization's locations and
        # ordered them in memory to hand back one page of them.
        assert 'Sort' not in [node['Node Type'] for node in nodes], _shape(plan)

        # The organization answers the filter, so the records of every other
        # organization are never touched.
        assert not [node for node in reads if node['Node Type'] == 'Seq Scan'], _shape(
            plan
        )
        assert [node['Node Type'] for node in reads] == ['Index Scan'] * len(reads), (
            _shape(plan)
        )
        assert [node.get('Index Name') for node in reads] == [_INDEX] * len(reads), (
            _shape(plan)
        )

        # Read, not returned: the location filter drops a little after the
        # index hands the rows over, and those rows were still read. A page
        # that read the whole organization to fill a hundred rows would fail
        # here whichever index it named.
        read = sum(
            node['Actual Rows'] + node.get('Rows Removed by Filter', 0)
            for node in reads
        )
        assert read < organization_stock.item_count // 4, _shape(plan)


class TestThePageIsWhatTheFixtureSeeded:
    async def test_the_page_is_the_newest_hundred_of_the_organization(
        self,
        real_async_db_session: AsyncSession,
        organization_stock: _OrganizationStock,
    ) -> None:
        db = real_async_db_session
        items, total = await _first_page(db, organization_stock)

        # Newest first, and only this organization's records: the neighbors'
        # stock is interleaved in write time with these, so a page that lost
        # the tenant would show theirs among the newest.
        assert [item.name for item in items] == organization_stock.expected_names
        assert {item.organization_id for item in items} == {organization_stock.org_id}

        # The footer counts the same set the page was cut from — the neighbors
        # hold five thousand records each and none of them is this number.
        assert total == organization_stock.item_count

        # Guard the guards: the plan assertions mean nothing over a table the
        # fixture never filled, so the neighbors are counted here as the rows
        # the answer leaves out.
        neighbors = await db.scalar(
            text(
                'SELECT count(*) FROM items WHERE organization_id != :org_id '
                "AND name LIKE 'Neighbor goods %'"
            ),
            {'org_id': organization_stock.org_id},
        )
        assert neighbors == _BYSTANDERS * _BYSTANDER_ITEMS
