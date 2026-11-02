"""A page deep in a long ledger costs what the first page costs.

The ledger paged with ``OFFSET``, and to hand back the page that starts at row
99,900 the database produced the 99,900 rows above it and threw them away. The
screen did not feel it at ten thousand movements; a warehouse that has been
running for a few years has ten times that, and nothing archives a movement.

Paging by the last row seen turns the page into a seek: the condition names
where the previous page ended, and the index on the ledger's sort expression
starts there. What is measured is the work the database reports for the
statement — the rows it read from the ledger to produce the page — because a
clock here measures the machine, not the query (see
``test_the_ledger_stays_quick_when_it_is_long.py`` for how that went). Buffers
are not the measure: how many pages the same rows sit on depends on how the
table was filled and on what else the worker's database has held, which made
the buffer count of one run differ from the next by a factor of thirty for the
same plan.

A hundred thousand movements, five to an instant, so every page boundary of a
page that size cuts through a group that shares its date: the case where a
seek on the date alone would lose or repeat rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services import stock_moves_service

_LEDGER_SIZE = 100_000
_PAGE = 100
#: Movements that share one instant, so a page boundary can fall inside a group.
_TIES = 5
_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

#: Rows the database may read from the ledger to produce one page: the page,
#: the movements that share the instant it starts at, and no more.
_ROWS_PER_PAGE = _PAGE + 2 * _TIES


class _Ledger:
    def __init__(self) -> None:
        self.org_id: UUID


@pytest.fixture
async def long_ledger(real_async_db_session: AsyncSession) -> _Ledger:
    db = real_async_db_session
    ledger = _Ledger()
    org = Organization(
        name=f'Deep {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    ledger.org_id = org.id
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'deep_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    product = ProductTemplate(name='Product', organization_id=org.id)
    db.add_all([location, product])
    await db.flush()

    # Generated in the database: sending a hundred thousand rows through the
    # driver would make the fixture the slow part of the file. Every tenth
    # movement carries no completion date, so the fallback half of the sort
    # expression is part of what is measured.
    await db.execute(
        text(
            """
            INSERT INTO stock_moves (
                id, organization_id, product_template_id, to_location_id,
                quantity, state, reference_type, reference_id, created_by,
                created_at, updated_at, completed_at
            )
            SELECT
                gen_random_uuid(), :org, :product, :location,
                1, 'done', 'item', gen_random_uuid(), :user,
                CAST(:now AS timestamptz) - (n / CAST(:ties AS integer)) * interval '1 minute',
                CAST(:now AS timestamptz) - (n / CAST(:ties AS integer)) * interval '1 minute',
                CASE WHEN n % 10 = 3 THEN NULL
                     ELSE CAST(:now AS timestamptz) - (n / CAST(:ties AS integer)) * interval '1 minute' END
            FROM generate_series(0, CAST(:last AS integer)) AS n
            """
        ),
        {
            'org': org.id,
            'product': product.id,
            'location': location.id,
            'user': user.id,
            'now': _NOW,
            'ties': _TIES,
            'last': _LEDGER_SIZE - 1,
        },
    )
    await db.commit()
    # Left uncommitted on purpose, as in the ten-thousand-row file: the lock
    # keeps an autovacuum that began before the seed from replacing these
    # statistics with an empty picture of the table.
    await db.execute(text('ANALYZE stock_moves'))
    return ledger


#: A different ledger: a hundred thousand movements of which fifty thousand
#: share ONE instant — a bulk import, a stocktake closed in one go — with
#: ordinary history above it and below it. The group is not bounded by the page
#: size, so a page that starts inside it is the case a seek on the date alone
#: handles badly and a ten-in-a-group ledger never shows.
_BULK_FROM = 30_000
_BULK_TO = 80_000


@pytest.fixture
async def bulk_ledger(real_async_db_session: AsyncSession) -> _Ledger:
    db = real_async_db_session
    ledger = _Ledger()
    org = Organization(
        name=f'Bulk {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    ledger.org_id = org.id
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'bulk_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    product = ProductTemplate(name='Product', organization_id=org.id)
    db.add_all([location, product])
    await db.flush()

    # Newest 30,000: five to an instant. Then fifty thousand at one instant,
    # a tenth of them without a completion date (their creation date is the
    # same instant, so they belong to the group). Then the oldest 20,000.
    await db.execute(
        text(
            """
            INSERT INTO stock_moves (
                id, organization_id, product_template_id, to_location_id,
                quantity, state, reference_type, reference_id, created_by,
                created_at, updated_at, completed_at
            )
            SELECT
                gen_random_uuid(), :org, :product, :location,
                1, 'done', 'item', gen_random_uuid(), :user,
                moment, moment,
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
            'product': product.id,
            'location': location.id,
            'user': user.id,
            'now': _NOW,
            'ties': _TIES,
            'last': _LEDGER_SIZE - 1,
            'bulk_from': _BULK_FROM,
            'bulk_to': _BULK_TO,
        },
    )
    await db.commit()
    await db.execute(text('ANALYZE stock_moves'))
    return ledger


def _nodes(plan: dict) -> list[dict]:
    found = [plan]
    for child in plan.get('Plans', []):
        found.extend(_nodes(child))
    return found


def _buffers(plans: list[dict]) -> int:
    return sum(
        plan.get('Shared Hit Blocks', 0) + plan.get('Shared Read Blocks', 0)
        for plan in plans
    )


def _rows_read(plans: list[dict]) -> int:
    """Rows the statements read from the ledger itself, kept or thrown away.

    The ledger is read by a scan whose rows are either returned or removed by
    a filter, and a node may run more than once: ``Actual Rows`` and
    ``Rows Removed by Filter`` are per run.
    """
    return sum(
        (node.get('Actual Rows', 0) + node.get('Rows Removed by Filter', 0))
        * node.get('Actual Loops', 1)
        for plan in plans
        for node in _nodes(plan)
        if node.get('Relation Name') == 'stock_moves'
    )


async def _page_plan(db: AsyncSession, call) -> tuple[object, list[dict]]:
    """Run *call*, then ``EXPLAIN (ANALYZE, BUFFERS)`` every statement that ordered the page.

    A page that starts inside a group of movements sharing one instant is read
    in two steps (the rest of the group, then the older movements), so there
    can be more than one; what a page costs is what they cost together.
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
        if 'ORDER BY' in statement and 'FROM stock_moves' in statement
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
    """The date and id of the movement at *position* in the ledger's order."""
    row = (
        await db.execute(
            text(
                """
                SELECT coalesce(completed_at, created_at) AS moved_at, id
                FROM stock_moves
                WHERE organization_id = :org
                ORDER BY coalesce(completed_at, created_at) DESC, id
                OFFSET :position LIMIT 1
                """
            ),
            {'org': org_id, 'position': position},
        )
    ).one()
    return row.moved_at, row.id


@pytest.mark.integration
class TestADeepPageIsASeek:
    async def test_the_page_near_the_end_reads_the_rows_the_first_page_reads(
        self, real_async_db_session: AsyncSession, long_ledger: _Ledger
    ) -> None:
        db = real_async_db_session
        (first_rows, total), first = await _page_plan(
            db,
            lambda: stock_moves_service.list_rows_for_org_async(
                db, long_ledger.org_id, limit=_PAGE
            ),
        )
        # The page that starts a hundred rows from the end: the worst place
        # for an offset, and no different from any other for a seek.
        after_moved_at, after_id = await _row_at(
            db, long_ledger.org_id, _LEDGER_SIZE - _PAGE - 1
        )
        (deep_rows, deep_total), deep = await _page_plan(
            db,
            lambda: stock_moves_service.list_rows_for_org_async(
                db,
                long_ledger.org_id,
                limit=_PAGE,
                after=(after_moved_at, after_id),
                known_total=total,
            ),
        )

        assert total == _LEDGER_SIZE
        assert deep_total == _LEDGER_SIZE
        assert len(first_rows) == _PAGE
        assert [row.id for row in deep_rows] == await _ids_after(
            db, long_ledger.org_id, _LEDGER_SIZE - _PAGE - 1, _PAGE
        )
        assert _rows_read(first) <= _ROWS_PER_PAGE, _rows_read(first)
        assert _rows_read(deep) <= _ROWS_PER_PAGE, (
            _rows_read(first),
            _rows_read(deep),
            _buffers(deep),
        )

    async def test_the_deep_page_is_read_off_the_index_without_a_sort(
        self, real_async_db_session: AsyncSession, long_ledger: _Ledger
    ) -> None:
        db = real_async_db_session
        after_moved_at, after_id = await _row_at(
            db, long_ledger.org_id, _LEDGER_SIZE // 2
        )

        (rows, _total), plans = await _page_plan(
            db,
            lambda: stock_moves_service.list_rows_for_org_async(
                db,
                long_ledger.org_id,
                limit=_PAGE,
                after=(after_moved_at, after_id),
                known_total=_LEDGER_SIZE,
            ),
        )

        nodes = [node for plan in plans for node in _nodes(plan)]
        indexes = {node.get('Index Name') for node in nodes}
        # The names and units the rows are joined to are small tables the
        # planner may read however it likes; what must not be read whole, or
        # sorted wide, is the ledger itself.
        scans = {
            node['Node Type']
            for node in nodes
            if node.get('Relation Name') == 'stock_moves'
        }
        sorts = [
            node.get('Actual Rows', 0)
            for node in nodes
            if node['Node Type'] in {'Sort', 'Incremental Sort'}
        ]
        assert [row.id for row in rows] == await _ids_after(
            db, long_ledger.org_id, _LEDGER_SIZE // 2, _PAGE
        )
        assert 'Seq Scan' not in scans, scans
        assert all(rows_sorted <= 2 * _PAGE for rows_sorted in sorts), sorts
        assert 'ix_stock_moves_org_moved_at' in indexes, indexes
        assert _rows_read(plans) <= _ROWS_PER_PAGE, _rows_read(plans)

    async def test_the_offset_page_it_replaces_reads_the_ledger_above_it(
        self, real_async_db_session: AsyncSession, long_ledger: _Ledger
    ) -> None:
        """The contrast the other two tests stand on, so they cannot pass by default.

        The same page asked for by position reads a great many more rows of the
        ledger than the first page. If this ever stops being true, the ratio the
        tests above hold the seek to has stopped meaning anything.
        """
        db = real_async_db_session
        _, first = await _page_plan(
            db,
            lambda: stock_moves_service.list_rows_for_org_async(
                db, long_ledger.org_id, limit=_PAGE, known_total=_LEDGER_SIZE
            ),
        )
        _, by_offset = await _page_plan(
            db,
            lambda: stock_moves_service.list_rows_for_org_async(
                db,
                long_ledger.org_id,
                limit=_PAGE,
                offset=_LEDGER_SIZE - _PAGE,
                known_total=_LEDGER_SIZE,
            ),
        )

        assert _rows_read(by_offset) > 50 * _rows_read(first), (
            _rows_read(first),
            _rows_read(by_offset),
        )


async def _ids_after(
    db: AsyncSession, org_id: UUID, position: int, limit: int
) -> list[UUID]:
    """The ids that follow *position* in the ledger's order, by the plain definition."""
    rows = await db.execute(
        text(
            """
            SELECT id FROM stock_moves
            WHERE organization_id = :org
            ORDER BY coalesce(completed_at, created_at) DESC, id
            OFFSET :start LIMIT :limit
            """
        ),
        {'org': org_id, 'start': position + 1, 'limit': limit},
    )
    return [row.id for row in rows]


@pytest.mark.integration
class TestAPageInsideALargeGroupOfTiedMovements:
    async def test_every_such_page_is_the_right_rows_read_at_the_price_of_a_page(
        self, real_async_db_session: AsyncSession, bulk_ledger: _Ledger
    ) -> None:
        """Fifty thousand movements share an instant; the pages through it are flat.

        Where the previous page ended decides the cost, and so the positions
        are the ones that differ: just before the group, in its first rows, in
        its middle (where a condition that cannot start inside the group
        reads half of it), at its very end, one page that leaves it for older
        history, and deep in that history. Each is checked for the rows it
        returns — the exact ids the plain definition of the order gives — and
        for the rows it read to get them, against the same budget as a page in
        a ledger with no large group at all.
        """
        db = real_async_db_session
        positions = [
            _BULK_FROM - 10,
            _BULK_FROM,
            _BULK_FROM + 1,
            (_BULK_FROM + _BULK_TO) // 2,
            _BULK_TO - _PAGE // 2,
            _BULK_TO - 1,
            _LEDGER_SIZE - _PAGE - 1,
        ]
        for position in positions:
            after = await _row_at(db, bulk_ledger.org_id, position)

            (rows, total), plans = await _page_plan(
                db,
                partial(
                    stock_moves_service.list_rows_for_org_async,
                    db,
                    bulk_ledger.org_id,
                    limit=_PAGE,
                    after=after,
                    known_total=_LEDGER_SIZE,
                ),
            )

            assert [row.id for row in rows] == await _ids_after(
                db, bulk_ledger.org_id, position, _PAGE
            ), position
            assert total == _LEDGER_SIZE
            assert _rows_read(plans) <= _ROWS_PER_PAGE, (position, _rows_read(plans))

    async def test_walking_the_whole_group_loses_and_repeats_nothing(
        self, real_async_db_session: AsyncSession, bulk_ledger: _Ledger
    ) -> None:
        db = real_async_db_session
        position = _BULK_FROM - 3
        after = await _row_at(db, bulk_ledger.org_id, position)
        seen: list[UUID] = []
        while len(seen) < _BULK_TO - _BULK_FROM + 6:
            rows, _ = await stock_moves_service.list_rows_for_org_async(
                db, bulk_ledger.org_id, limit=1_000, after=after, known_total=1
            )
            seen.extend(row.id for row in rows)
            after = (rows[-1].completed_at or rows[-1].created_at, rows[-1].id)

        assert seen == await _ids_after(db, bulk_ledger.org_id, position, len(seen))
