"""The movement ledger with ten thousand movements in it.

Every warehouse that uses this product will pass ten thousand movements,
most of them within the first year, and the ledger is the one screen that
grows without bound — nothing archives a movement, because the point of a
ledger is that it keeps everything.

The list sorts by ``coalesce(completed_at, created_at) DESC, id``, and that
expression is the trap: the date a movement is *about* is neither of those
columns on its own, so no ordinary index on either one can serve the sort.
Without an index over the expression itself Postgres reads the whole table
and sorts it in memory to hand back fifty rows.

What is measured is the shape of the work, on the statements the service
actually sends: how many there are, and what plan each page read gets. Both
fail on the regressions this file exists for — a lost index turns the page
into a scan and a sort, a name resolved per row turns two statements into
fifty-two — and neither depends on who else is using the machine.

This used to be a clock: three hundred milliseconds per read. It was red at
1117 ms on a host at load 73, on a branch that did not touch the ledger, and
green on the deep page whose plan *is* a full scan and a sort — so it flagged
the neighbours and missed the thing it was named for.

Note the seeding goes around the service, straight into the table. The
development stack runs with ``fsync=off``, so none of this is about write
speed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services import stock_moves_service

#: Ten thousand is the figure the plan named, and roughly a year of a busy
#: single-site warehouse: thirty receipts and picks a day.
_LEDGER_SIZE = 10_000

#: Movements of a product the warehouse barely handles — the sparse case.
_RARE_MOVEMENTS = 3

#: One page as the screen asks for it.
_PAGE = 50

#: Statements one page read may send: the count and the page itself. A name
#: resolved per row would add one a row, fifty on a page.
_STATEMENTS = 2

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class _BusyWarehouse:
    def __init__(self) -> None:
        self.org_id: UUID
        self.product_ids: list[UUID]
        self.location_ids: list[UUID]
        self.document_id: UUID
        self.rare_product_id: UUID


@pytest.fixture
async def busy_warehouse(real_async_db_session: AsyncSession) -> _BusyWarehouse:
    """Ten thousand movements over three products and four places."""
    db = real_async_db_session
    fixture = _BusyWarehouse()

    org = Organization(
        name=f'Busy {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    fixture.org_id = org.id

    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'busy_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()

    locations = [
        StorageLocation(
            name=f'Aisle {n}',
            organization_id=org.id,
            storage_type_id=storage_type.id,
            created_by=user.id,
        )
        for n in range(4)
    ]
    products = [
        ProductTemplate(name=f'Product {n}', organization_id=org.id) for n in range(3)
    ]
    # Something the warehouse handled three times all year. The filtered
    # reads above are dense — one row in three matches — and a dense filter
    # is the easy case for an index that carries the sort order.
    rare = ProductTemplate(name='Rare product', organization_id=org.id)
    products.append(rare)
    db.add_all([*locations, *products])
    await db.flush()

    fixture.location_ids = [location.id for location in locations]
    fixture.product_ids = [product.id for product in products[:3]]
    fixture.rare_product_id = rare.id
    fixture.document_id = uuid4()

    # One in ten movements carries the document the filter asks about, so the
    # narrowed read still returns a thousand rows to page through.
    rows = [
        {
            'id': uuid4(),
            'organization_id': org.id,
            'product_template_id': fixture.product_ids[n % 3],
            'from_location_id': fixture.location_ids[n % 4] if n % 2 else None,
            'to_location_id': None if n % 2 else fixture.location_ids[n % 4],
            'quantity': Decimal('1.000'),
            'state': 'done',
            'reference_type': 'document',
            'reference_id': fixture.document_id if n % 10 == 0 else uuid4(),
            'created_by': user.id,
            'created_at': _NOW - timedelta(minutes=n),
            'updated_at': _NOW - timedelta(minutes=n),
            # A tenth of the ledger never carried a completion date, so the
            # fallback half of the expression is exercised too.
            'completed_at': None if n % 10 == 3 else _NOW - timedelta(minutes=n),
        }
        for n in range(_LEDGER_SIZE)
    ]
    # Three of them, one at each end of the ledger and one in the middle, so
    # the rare-product read has to walk the whole index to collect them.
    rows.extend(
        {
            'id': uuid4(),
            'organization_id': org.id,
            'product_template_id': rare.id,
            'from_location_id': None,
            'to_location_id': fixture.location_ids[0],
            'quantity': Decimal('1.000'),
            'state': 'done',
            'reference_type': 'manual',
            'reference_id': None,
            'created_by': user.id,
            'created_at': _NOW - timedelta(minutes=minutes),
            'updated_at': _NOW - timedelta(minutes=minutes),
            'completed_at': _NOW - timedelta(minutes=minutes),
        }
        for minutes in (1, _LEDGER_SIZE // 2, _LEDGER_SIZE - 1)
    )
    for start in range(0, len(rows), 2_000):
        await db.execute(insert(StockMove), rows[start : start + 2_000])
    await db.commit()

    # Planning off stale statistics is planning off a table Postgres thinks is
    # empty, which chooses a sequential scan whatever indexes exist. The
    # ANALYZE is deliberately left uncommitted: it holds the table's
    # ShareUpdateExclusive lock until the test's teardown, so an autovacuum
    # that began before these rows landed — carrying an empty picture of the
    # table — cannot commit that picture between this refresh and the read
    # that plans on it. Committing here was the window.
    await db.execute(text('ANALYZE stock_moves'))
    return fixture


class _Read:
    """What one service call sent, and the plan the database gives each page read."""

    def __init__(self, statements: list[str], plans: list[dict]) -> None:
        self.statements = statements
        self.plans = plans

    def page_plan(self) -> dict:
        """The plan of the one statement that orders the ledger."""
        pages = [
            plan
            for statement, plan in zip(self.statements, self.plans, strict=True)
            if 'ORDER BY' in statement and 'FROM stock_moves' in statement
        ]
        assert len(pages) == 1, self.statements
        return pages[0]


def _nodes(plan: dict) -> list[dict]:
    found = [plan]
    for child in plan.get('Plans', []):
        found.extend(_nodes(child))
    return found


def _scans_of_stock_moves(plan: dict) -> set[str]:
    return {
        node['Node Type']
        for node in _nodes(plan)
        if node.get('Relation Name') == 'stock_moves'
    }


async def _read(
    db: AsyncSession, call, *, sorting: bool = False
) -> tuple[object, _Read]:
    """Run *call* and explain every statement it sent, with its own parameters.

    The plans are asked for after the call, on the statements as the driver
    received them — not on a hand-written query that only resembles them.

    They are asked for with sorting switched off unless *sorting* says
    otherwise. The question a page read answers here is whether the ordering
    index can serve its order, and a lost index still ends in a Sort: switched
    off, a sort is only priced out of reach, never made impossible. What the
    switch takes away is the statistics' say. The index plan of the first page
    costs some 27 against some 300 for reading the organization and sorting
    it, so a Sort wins only on a picture of the table that does not know this
    organization's ten thousand rows — and the fixture's uncommitted ANALYZE
    did not keep every full run from planning on one.
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

    connection = await db.connection()
    if not sorting:
        await connection.exec_driver_sql('SET LOCAL enable_sort = off')
        await connection.exec_driver_sql('SET LOCAL enable_incremental_sort = off')
    plans = []
    for statement, parameters in sent:
        explained = await connection.exec_driver_sql(
            f'EXPLAIN (FORMAT JSON) {statement}', parameters
        )
        plans.append(explained.scalar()[0]['Plan'])
    await connection.exec_driver_sql('RESET enable_sort')
    await connection.exec_driver_sql('RESET enable_incremental_sort')
    return result, _Read([statement for statement, _ in sent], plans)


class TestAPageReadStaysTheSameShapeAtTenThousand:
    async def test_the_first_page_of_the_whole_ledger(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        (rows, total), read = await _read(
            real_async_db_session,
            lambda: stock_moves_service.list_rows_for_org_async(
                real_async_db_session, busy_warehouse.org_id, limit=_PAGE
            ),
        )

        assert total == _LEDGER_SIZE + _RARE_MOVEMENTS
        assert len(rows) == _PAGE
        assert len(read.statements) == _STATEMENTS, read.statements
        _assert_served_by_the_ordering_index(read.page_plan())

    async def test_a_racing_analyze_cannot_replace_the_statistics_the_read_plans_on(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        """The picture the read plans on must not be replaceable under it.

        Every test here leaves ten thousand rows for autovacuum to dispose
        of, and on a loaded full run it analyzes this very table while the
        fixture seeds it. An autovacuum that began before the seed committed
        carries an empty picture of the table; committed, that picture lands
        between the seed and the read and the plan falls back to a sort —
        red on a branch that touched nothing. So the statistics the read
        plans on are the fixture's own, held uncommitted until the test
        ends; a second session's ANALYZE of the same table cannot complete
        while it runs.
        """
        racing = create_async_engine(
            settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1),
            poolclass=NullPool,
        )
        try:
            factory = async_sessionmaker(
                racing, class_=AsyncSession, expire_on_commit=False
            )
            async with factory() as other:
                await other.execute(text("SET statement_timeout = '500ms'"))
                with pytest.raises(DBAPIError):
                    await other.execute(text('ANALYZE stock_moves'))
                await other.rollback()
        finally:
            await racing.dispose()

        (rows, total), read = await _read(
            real_async_db_session,
            lambda: stock_moves_service.list_rows_for_org_async(
                real_async_db_session, busy_warehouse.org_id, limit=_PAGE
            ),
        )

        assert total == _LEDGER_SIZE + _RARE_MOVEMENTS
        assert len(rows) == _PAGE
        _assert_served_by_the_ordering_index(read.page_plan())

    async def test_the_page_filtered_by_product(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        (rows, total), read = await _read(
            real_async_db_session,
            lambda: stock_moves_service.list_rows_for_org_async(
                real_async_db_session,
                busy_warehouse.org_id,
                product_template_id=busy_warehouse.product_ids[0],
                limit=_PAGE,
            ),
        )

        assert total > 0
        assert len(rows) == _PAGE
        assert len(read.statements) == _STATEMENTS, read.statements
        _assert_served_by_the_ordering_index(read.page_plan())

    async def test_the_page_filtered_by_location(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        (rows, total), read = await _read(
            real_async_db_session,
            lambda: stock_moves_service.list_rows_for_org_async(
                real_async_db_session,
                busy_warehouse.org_id,
                location_id=busy_warehouse.location_ids[0],
                limit=_PAGE,
            ),
        )

        assert total > 0
        assert len(rows) == _PAGE
        # A place stands for itself and everything under it, resolved once.
        assert len(read.statements) == _STATEMENTS + 1, read.statements
        _assert_served_by_the_ordering_index(read.page_plan())

    async def test_the_page_filtered_by_document(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        (rows, total), read = await _read(
            real_async_db_session,
            lambda: stock_moves_service.list_rows_for_org_async(
                real_async_db_session,
                busy_warehouse.org_id,
                reference_type='document',
                reference_id=busy_warehouse.document_id,
                limit=_PAGE,
            ),
        )

        assert total == _LEDGER_SIZE // 10
        assert len(rows) == _PAGE
        assert len(read.statements) == _STATEMENTS, read.statements
        _assert_served_by_the_ordering_index(read.page_plan())

    async def test_the_page_filtered_by_a_product_with_almost_no_movements(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        """The sparse filter, which is the hard one for the ordering index.

        Three matches in ten thousand cannot be found near the top of the
        ledger, so the database rightly reaches for the product's own index
        and sorts what it finds. That sort is fine — it holds three rows. What
        would not be fine is the table read end to end to find them.
        """
        (rows, total), read = await _read(
            real_async_db_session,
            lambda: stock_moves_service.list_rows_for_org_async(
                real_async_db_session,
                busy_warehouse.org_id,
                product_template_id=busy_warehouse.rare_product_id,
                limit=_PAGE,
            ),
            sorting=True,
        )

        assert total == _RARE_MOVEMENTS
        assert len(rows) == _RARE_MOVEMENTS
        assert len(read.statements) == _STATEMENTS, read.statements
        scans = _scans_of_stock_moves(read.page_plan())
        assert scans, read.page_plan()
        assert not scans & {'Seq Scan'}, scans

    async def test_the_last_page_holds_the_oldest_movements(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        """Deep paging, asked what can honestly be asked of it.

        An offset is not a seek: to hand back the last fifty rows the database
        produces every row before them, and at this depth it chooses a full
        scan and a sort, which is the right plan for the question. The plan
        is therefore not the claim here. The claims are that the end of the
        ledger is really the oldest of it, and that reaching it costs the same
        two statements as the first page.
        """
        (rows, _total), read = await _read(
            real_async_db_session,
            lambda: stock_moves_service.list_rows_for_org_async(
                real_async_db_session,
                busy_warehouse.org_id,
                limit=_PAGE,
                offset=_LEDGER_SIZE + _RARE_MOVEMENTS - _PAGE,
            ),
        )

        assert len(rows) == _PAGE
        assert len(read.statements) == _STATEMENTS, read.statements
        oldest = _NOW - timedelta(minutes=_LEDGER_SIZE - 1)
        assert min(row.created_at for row in rows) == oldest


class TestThePlanIsTheIndexsNotTheStatistics:
    """What the plan assertions above answer to, and what they do not.

    Both tests change the table inside the test's own transaction, which the
    session fixture rolls back.
    """

    async def test_an_empty_picture_of_the_table_does_not_sort_the_page(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        """The picture an autovacuum takes before the seed commits.

        The rows deleted here are invisible to the ANALYZE that follows, as
        uncommitted rows are to an autovacuum's: it records a table with
        nothing in it. Planned on that, with sorting allowed, the first page
        is read off another index and sorted — the red these tests used to
        show on a loaded full run while passing alone.
        """
        db = real_async_db_session
        await db.execute(text('DELETE FROM stock_moves'))
        await db.execute(text('ANALYZE stock_moves'))

        _, read = await _read(
            db,
            lambda: stock_moves_service.list_rows_for_org_async(
                db, busy_warehouse.org_id, limit=_PAGE
            ),
        )

        _assert_served_by_the_ordering_index(read.page_plan())

    async def test_a_lost_ordering_index_still_ends_in_a_sort(
        self, real_async_db_session: AsyncSession, busy_warehouse: _BusyWarehouse
    ) -> None:
        """Sorting switched off prices a sort out of reach; it does not forbid
        one. Without the index nothing else can hand the page back in order."""
        db = real_async_db_session
        await db.execute(text('DROP INDEX ix_stock_moves_org_moved_at'))

        _, read = await _read(
            db,
            lambda: stock_moves_service.list_rows_for_org_async(
                db, busy_warehouse.org_id, limit=_PAGE
            ),
        )

        assert 'Sort' in {node['Node Type'] for node in _nodes(read.page_plan())}


def _assert_served_by_the_ordering_index(plan: dict) -> None:
    """The page is read in ledger order off the index, not sorted after a read."""
    node_types = {node['Node Type'] for node in _nodes(plan)}
    indexes = {node.get('Index Name') for node in _nodes(plan)}
    # A "Sort" here means the whole organization's ledger was read and ordered
    # to produce fifty rows — cheap at ten thousand, ruinous at a million.
    assert not node_types & {'Sort', 'Incremental Sort'}, node_types
    assert 'ix_stock_moves_org_moved_at' in indexes, indexes
