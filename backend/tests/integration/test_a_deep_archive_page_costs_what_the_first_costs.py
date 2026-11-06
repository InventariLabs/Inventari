"""A page deep in a long archive costs what the first page costs.

The archived products list paged with ``OFFSET``: to hand back the page that
starts at row 19,900 the database produced the 19,900 rows above it and threw
them away, and nothing deletes an archived record, so that only grows. Paging
by the last row seen turns the page into a seek on the index that is the
archive's order (``ix_items_org_archived_at``).

What is measured is the work the database reports for the statement — the
rows it read from ``items`` to produce the page — and not a clock or buffers:
a clock measures the machine, and how many buffers the same rows sit on
depends on how the table was filled (see
``test_a_deep_ledger_page_costs_what_the_first_costs.py``, which this file
follows).

The archive holds twenty thousand records: the newest six thousand archived
five to an instant, then ten thousand archived at ONE instant — a bulk
archive, larger than any page — then the oldest four thousand, five to an
instant again. Every tenth record carries no archive date, so the creation
date it falls back to is part of what is measured. Two thousand live records
of the same organization sit in the same table and must not be read.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services.items._query_special import get_archived_items_async

_ARCHIVED = 20_000
_LIVE = 2_000
_PAGE = 100
#: Records archived at one instant in the ordinary stretches.
_TIES = 5
_BULK_FROM = 6_000
_BULK_TO = 16_000
_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

#: Rows the database may read from ``items`` to produce one page: the page,
#: the records that share the instant it starts at, and no more.
_ROWS_PER_PAGE = _PAGE + 2 * _TIES


class _Archive:
    def __init__(self) -> None:
        self.org_id: UUID
        self.location_id: UUID


@pytest.fixture
async def long_archive(real_async_db_session: AsyncSession) -> _Archive:
    db = real_async_db_session
    archive = _Archive()
    org = Organization(
        name=f'Archive {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    archive.org_id = org.id
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'archive_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Pantry',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.flush()
    archive.location_id = location.id

    # Generated in the database: sending twenty thousand rows through the
    # driver would make the fixture the slow part of the file. A record that
    # carries an archive date was made a year before it; one that carries
    # none was made at the instant it sorts by.
    await db.execute(
        text(
            """
            INSERT INTO items (
                id, organization_id, storage_location_id, name, quantity,
                added_date, is_deleted, is_catalog_entry,
                created_at, updated_at, deleted_at
            )
            SELECT
                gen_random_uuid(), :org, :location, 'Archived ' || n, 0,
                CAST(:now AS date), true, false,
                CASE WHEN n % 10 = 3 THEN moment ELSE moment - interval '365 days' END,
                moment,
                CASE WHEN n % 10 = 3 THEN NULL ELSE moment END
            FROM (
                SELECT n,
                    CASE
                        WHEN n < :bulk_from
                            THEN CAST(:now AS timestamptz)
                                - (n / CAST(:ties AS integer)) * interval '1 minute'
                        WHEN n < :bulk_to
                            THEN CAST(:now AS timestamptz) - interval '10000 minutes'
                        ELSE CAST(:now AS timestamptz)
                            - interval '20000 minutes'
                            - ((n - :bulk_to) / CAST(:ties AS integer))
                                * interval '1 minute'
                    END AS moment
                FROM generate_series(0, CAST(:last AS integer)) AS n
            ) AS generated
            """
        ),
        {
            'org': org.id,
            'location': location.id,
            'now': _NOW,
            'ties': _TIES,
            'last': _ARCHIVED - 1,
            'bulk_from': _BULK_FROM,
            'bulk_to': _BULK_TO,
        },
    )
    await db.execute(
        text(
            """
            INSERT INTO items (
                id, organization_id, storage_location_id, name, quantity,
                added_date, is_deleted, is_catalog_entry, created_at, updated_at
            )
            SELECT
                gen_random_uuid(), :org, :location, 'Live ' || n, 0,
                CAST(:now AS date), false, false,
                CAST(:now AS timestamptz), CAST(:now AS timestamptz)
            FROM generate_series(1, CAST(:live AS integer)) AS n
            """
        ),
        {'org': org.id, 'location': location.id, 'now': _NOW, 'live': _LIVE},
    )
    await db.commit()
    # Left uncommitted on purpose, as in the ledger's file: the lock keeps an
    # autovacuum that began before the seed from replacing these statistics
    # with an empty picture of the table.
    await db.execute(text('ANALYZE items'))
    return archive


def _nodes(plan: dict) -> list[dict]:
    found = [plan]
    for child in plan.get('Plans', []):
        found.extend(_nodes(child))
    return found


def _rows_read(plans: list[dict]) -> int:
    """Rows the statements read from ``items``, kept or thrown away by a filter."""
    return sum(
        (node.get('Actual Rows', 0) + node.get('Rows Removed by Filter', 0))
        * node.get('Actual Loops', 1)
        for plan in plans
        for node in _nodes(plan)
        if node.get('Relation Name') == 'items'
    )


async def _page_plan(
    db: AsyncSession, call: Callable[[], Awaitable[tuple[list[Item], int]]]
) -> tuple[tuple[list[Item], int], list[dict]]:
    """Run *call*, then ``EXPLAIN (ANALYZE, BUFFERS)`` every statement that ordered the page.

    A page that starts inside a group of records sharing one instant is read
    in two steps (the rest of the group, then the older records), so there can
    be more than one; what a page costs is what they cost together.
    """
    sent: list[tuple[str, object]] = []
    engine = db.bind.sync_engine

    def capture(conn, cursor, statement, parameters, context, executemany):
        sent.append((statement, parameters))

    event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = await call()
    finally:
        event.remove(engine, 'before_cursor_execute', capture)

    pages = [
        (statement, parameters)
        for statement, parameters in sent
        if 'ORDER BY' in statement and 'FROM items' in statement
    ]
    assert 1 <= len(pages) <= 2, [statement for statement, _ in sent]
    connection = await db.connection()
    plans = []
    for statement, parameters in pages:
        explained = await connection.exec_driver_sql(
            f'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}', parameters
        )
        plans.append(explained.scalar()[0]['Plan'])
    return result, plans


async def _row_at(
    db: AsyncSession, org_id: UUID, position: int
) -> tuple[datetime, UUID]:
    """The date and id of the archived record at *position* in the archive's order."""
    row = (
        await db.execute(
            text(
                """
                SELECT coalesce(deleted_at, created_at) AS archived_at, id
                FROM items
                WHERE organization_id = :org AND is_deleted
                ORDER BY coalesce(deleted_at, created_at) DESC, id
                OFFSET :position LIMIT 1
                """
            ),
            {'org': org_id, 'position': position},
        )
    ).one()
    return row.archived_at, row.id


async def _ids_after(
    db: AsyncSession, org_id: UUID, position: int, limit: int
) -> list[UUID]:
    """The ids that follow *position* in the archive's order, by the plain definition."""
    rows = await db.execute(
        text(
            """
            SELECT id FROM items
            WHERE organization_id = :org AND is_deleted
            ORDER BY coalesce(deleted_at, created_at) DESC, id
            OFFSET :start LIMIT :limit
            """
        ),
        {'org': org_id, 'start': position + 1, 'limit': limit},
    )
    return [row.id for row in rows]


def _page(
    db: AsyncSession, archive: _Archive, **kwargs: object
) -> Callable[[], Awaitable[tuple[list[Item], int]]]:
    return partial(
        get_archived_items_async,
        db,
        [archive.location_id],
        organization_id=archive.org_id,
        limit=_PAGE,
        **kwargs,
    )


@pytest.mark.integration
class TestADeepPageIsASeek:
    async def test_the_page_near_the_end_reads_the_rows_the_first_page_reads(
        self, real_async_db_session: AsyncSession, long_archive: _Archive
    ) -> None:
        db = real_async_db_session
        (first_rows, total), first = await _page_plan(db, _page(db, long_archive))
        # The page that starts a hundred rows from the end: the worst place
        # for an offset, and no different from any other for a seek.
        position = _ARCHIVED - _PAGE - 1
        after = await _row_at(db, long_archive.org_id, position)
        (deep_rows, deep_total), deep = await _page_plan(
            db, _page(db, long_archive, after=after, known_total=total)
        )

        assert total == _ARCHIVED
        assert deep_total == _ARCHIVED
        assert [row.id for row in first_rows] == await _ids_after(
            db, long_archive.org_id, -1, _PAGE
        )
        assert [row.id for row in deep_rows] == await _ids_after(
            db, long_archive.org_id, position, _PAGE
        )
        assert _rows_read(first) <= _ROWS_PER_PAGE, _rows_read(first)
        assert _rows_read(deep) <= _ROWS_PER_PAGE, _rows_read(deep)

    async def test_the_deep_page_is_read_off_the_index_without_a_sort(
        self, real_async_db_session: AsyncSession, long_archive: _Archive
    ) -> None:
        db = real_async_db_session
        position = _ARCHIVED - _PAGE * 10
        after = await _row_at(db, long_archive.org_id, position)

        (rows, _total), plans = await _page_plan(
            db, _page(db, long_archive, after=after, known_total=_ARCHIVED)
        )

        nodes = [node for plan in plans for node in _nodes(plan)]
        scans = {
            node['Node Type'] for node in nodes if node.get('Relation Name') == 'items'
        }
        sorts = [
            node.get('Actual Rows', 0)
            for node in nodes
            if node['Node Type'] in {'Sort', 'Incremental Sort'}
        ]
        assert [row.id for row in rows] == await _ids_after(
            db, long_archive.org_id, position, _PAGE
        )
        assert 'Seq Scan' not in scans, scans
        assert all(rows_sorted <= 2 * _PAGE for rows_sorted in sorts), sorts
        assert 'ix_items_org_archived_at' in {node.get('Index Name') for node in nodes}
        assert _rows_read(plans) <= _ROWS_PER_PAGE, _rows_read(plans)

    async def test_the_offset_page_it_replaces_reads_the_archive_above_it(
        self, real_async_db_session: AsyncSession, long_archive: _Archive
    ) -> None:
        """The contrast the other tests stand on, so they cannot pass by default.

        The same page asked for by position reads a great many more rows than
        the first page. If this ever stops being true, the budget the tests
        above hold the seek to has stopped meaning anything.
        """
        db = real_async_db_session
        _, first = await _page_plan(db, _page(db, long_archive, known_total=_ARCHIVED))
        _, by_offset = await _page_plan(
            db,
            _page(db, long_archive, offset=_ARCHIVED - _PAGE, known_total=_ARCHIVED),
        )

        assert _rows_read(by_offset) > 50 * _rows_read(first), (
            _rows_read(first),
            _rows_read(by_offset),
        )


@pytest.mark.integration
class TestAPageInsideALargeGroupOfTiedRecords:
    async def test_every_such_page_is_the_right_rows_read_at_the_price_of_a_page(
        self, real_async_db_session: AsyncSession, long_archive: _Archive
    ) -> None:
        """Ten thousand records share an instant; the pages through it are flat.

        Where the previous page ended decides the cost, so the positions are
        the ones that differ: just before the group, in its first rows, in its
        middle, at its very end, and one page that leaves it for older
        records. Each page is checked for the exact ids the plain definition
        of the order gives, and for the rows it read to get them.
        """
        db = real_async_db_session
        positions = [
            _BULK_FROM - 10,
            _BULK_FROM,
            _BULK_FROM + 1,
            (_BULK_FROM + _BULK_TO) // 2,
            _BULK_TO - _PAGE // 2,
            _BULK_TO - 1,
        ]
        for position in positions:
            after = await _row_at(db, long_archive.org_id, position)

            (rows, total), plans = await _page_plan(
                db, _page(db, long_archive, after=after, known_total=_ARCHIVED)
            )

            assert [row.id for row in rows] == await _ids_after(
                db, long_archive.org_id, position, _PAGE
            ), position
            assert total == _ARCHIVED
            assert _rows_read(plans) <= _ROWS_PER_PAGE, (position, _rows_read(plans))

    async def test_walking_the_whole_group_loses_and_repeats_nothing(
        self, real_async_db_session: AsyncSession, long_archive: _Archive
    ) -> None:
        db = real_async_db_session
        position = _BULK_FROM - 3
        after = await _row_at(db, long_archive.org_id, position)
        seen: list[UUID] = []
        while len(seen) < _BULK_TO - _BULK_FROM + 6:
            rows, _ = await get_archived_items_async(
                db,
                [long_archive.location_id],
                organization_id=long_archive.org_id,
                limit=1_000,
                after=after,
                known_total=1,
            )
            seen.extend(row.id for row in rows)
            last = rows[-1]
            after = (last.deleted_at or last.created_at, last.id)

        assert seen == await _ids_after(db, long_archive.org_id, position, len(seen))
