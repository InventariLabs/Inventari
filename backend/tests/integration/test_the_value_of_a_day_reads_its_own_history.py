"""The valuation of one day, asked of a year of history.

A cost layer is dated by the day it is *about* — its document's date, and its
write date only when there is no document behind it. That expression is
neither column on its own, so before this index the as-of report read the
organization's entire cost history and sorted it in memory to value a single
day: cheap at a few thousand layers, ruinous at a few hundred thousand, and
invisible to a test that only watches the clock.

The plan is the real assertion. A sequential scan over the layers, or a read
of layers the date excludes, means the whole history was replayed to answer a
question about a date — at any table size, and the answer is the same. The
rows-read comparison gives that a number: the reader's own year holds rows the
date excludes and rows that belong to other organizations, so a whole-table
read is visibly wider than the day being valued. The draw is replayed in the
database, as a window over each product's receipts, so the receipts the index
hands over are sorted by product there — the cut is what must stay narrow.
The report reads those rows by bitmap, each table page once, rather than one
row at a time in the index's order, so the plan is read under the same
setting the report sends, and the report is held to sending it.

The value and the statement count are the backstops. The value is what the
same layers add up to under the FIFO draw, counted from the fixture's own
rules — a plan that reads the right rows but drops one of them still fails
there. The count is what a year costs in round trips: two, whatever the
size of the history, so a lookup made per layer or per day shows up as a
number rather than as a slow afternoon.

That last one used to be a clock, 300 ms for the day's replay. It failed at
4000 ms on a host at load 60, on a branch that changed one frontend file, and
passed alone — it measured the neighbours, and the plan assertion above
already covered the regression it was named for.

Note the measurement is of reads only. The development stack runs with
``fsync=off``, so the seeding time in this file means nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.services.stock_as_of_service import (
    _READ_BY_BITMAP,
    _READ_IN_INDEX_ORDER_AGAIN,
    _foreign_receipts_async,
    _values_as_of,
    report_async,
)

pytestmark = pytest.mark.integration

#: One organization's year, at a busy single-site pace: twelve receipts and
#: six issues a day. Enough layers that the planner has to choose, in the
#: shape an instance that has been running for a while actually has.
_DAYS_OF_HISTORY = 365
_RECEIPTS_PER_DAY = 12
_ISSUES_PER_DAY = 6

#: Two neighbors on the same timeline. Their layers are what makes the plan
#: honest: a table holding only the reader's rows makes any index look
#: perfect, which is not the shape an instance has.
_BYSTANDERS = 2
_BYSTANDER_LAYERS = 4_000

#: The date being valued, as an accountant asks for it — a quarter behind, so
#: the day is neither the whole history nor none of it.
_AS_OF_DAYS_AGO = 90

#: One price for every receipt, so the day's value is arithmetic the fixture
#: can state without replaying the draw itself.
_UNIT_COST = Decimal('2.0000')

#: A price in somebody else's money, which the report refuses to value and
#: counts instead. Every ninety-seventh receipt carries one.
_FOREIGN_CURRENCY = 'EUR'
_ORG_CURRENCY = 'PLN'

_INDEX = 'ix_svl_org_direction_dated_at'

#: Round trips for one day's value: the draw over the dated receipts and what
#: left, and the refused count. Neither may grow with the history.
_STATEMENTS = 2

_NOW = datetime(2026, 6, 30, 0, 0, tzinfo=UTC)
_AS_OF = _NOW - timedelta(days=_AS_OF_DAYS_AGO)

#: A layer is three numbers and two dates, and the fixture needs thousands of
#: them: seeded row by row through the ORM, the fixture costs more than the
#: read it exists to measure. The database writes its own rows instead, and
#: the fixture keeps the rules — the day a row is about, the write-date
#: fallback, the foreign price — in the query below and in the arithmetic
#: above it.
_LAYER_COLUMNS = """
    id, organization_id, product_template_id, quantity, remaining_qty,
    unit_cost, total_value, document_date, currency, direction, created_at,
    cost_basis
"""

#: ``written`` is the day a row is about (its document's date), and the moment
#: it was written when there is no document behind it; a fifth of the receipts
#: and a fourth of the neighbors' layers have no document at all. The price
#: and the foreign currency come in as parameters, so the arithmetic above
#: reads the same two numbers the rows are written with.
_RECEIPTS_SQL = text(
    f"""
    INSERT INTO stock_valuation_layers ({_LAYER_COLUMNS})
    SELECT
        gen_random_uuid(), :org_id, :template_id,
        1.000, 1.000, CAST(:unit_cost AS numeric),
        CAST(:unit_cost AS numeric),
        CASE WHEN n % 5 = 0 THEN NULL ELSE w.written::date END,
        CASE WHEN (d * :per_day + n) % 97 = 0 THEN :foreign_currency ELSE NULL END,
        'IN', w.written, 'stated'
    FROM generate_series(0, CAST(:days AS int) - 1) AS d,
         generate_series(0, CAST(:per_day AS int) - 1) AS n,
         LATERAL (
             SELECT CAST(:now AS timestamptz) - make_interval(days => d)
                    + make_interval(mins => n) AS written
         ) AS w
    """
)

_ISSUES_SQL = text(
    f"""
    INSERT INTO stock_valuation_layers ({_LAYER_COLUMNS})
    SELECT
        gen_random_uuid(), :org_id, :template_id,
        1.000, 0, CAST(:unit_cost AS numeric), 0,
        w.written::date, NULL, 'OUT', w.written, 'stated'
    FROM generate_series(0, CAST(:days AS int) - 1) AS d,
         generate_series(0, CAST(:per_day AS int) - 1) AS n,
         LATERAL (
             SELECT CAST(:now AS timestamptz) - make_interval(days => d)
                    + make_interval(mins => n) AS written
         ) AS w
    """
)

_BYSTANDER_SQL = text(
    f"""
    INSERT INTO stock_valuation_layers ({_LAYER_COLUMNS})
    SELECT
        gen_random_uuid(), :org_id, :template_id,
        1.000, 1.000, CAST(:unit_cost AS numeric),
        CAST(:unit_cost AS numeric),
        CASE WHEN n % 4 = 0 THEN NULL ELSE w.written::date END,
        NULL, 'IN', w.written, 'stated'
    FROM generate_series(0, CAST(:count AS int) - 1) AS n,
         LATERAL (
             SELECT CAST(:now AS timestamptz) - make_interval(mins => n) AS written
         ) AS w
    """
)


class _YearOfHistory:
    def __init__(self) -> None:
        self.org_id: Any
        self.template_id: Any
        self.total_layers: int
        self.receipts_before_the_date: int
        self.issues_before_the_date: int
        self.foreign_before_the_date: int
        self.expected_value: Decimal


def _receipt_counts() -> tuple[int, int]:
    """How many of the reader's receipts the date admits, by currency.

    The same rule the seeding query writes with: a receipt is dated by its day
    of the year, and every ninety-seventh one is priced abroad. Counted here
    rather than read back, so the value below is an expectation and not a
    second reading of the same table.
    """
    included = 0
    foreign = 0
    for day in range(_AS_OF_DAYS_AGO, _DAYS_OF_HISTORY):
        for n in range(_RECEIPTS_PER_DAY):
            if (day * _RECEIPTS_PER_DAY + n) % 97 == 0:
                foreign += 1
            else:
                included += 1
    return included, foreign


@pytest.fixture
async def year_of_history(real_async_db_session: AsyncSession) -> _YearOfHistory:
    """A year of cost layers, for the reader and for two bystanders."""
    db = real_async_db_session
    fixture = _YearOfHistory()

    org = Organization(name=f'Year {uuid4().hex[:6]}', enabled_modules=['core'])
    bystanders = [
        Organization(name=f'Neighbor {n} {uuid4().hex[:6]}', enabled_modules=['core'])
        for n in range(_BYSTANDERS)
    ]
    db.add(org)
    db.add_all(bystanders)
    await db.commit()
    fixture.org_id = org.id

    template = ProductTemplate(name='Rye flour', organization_id=org.id)
    neighbor_templates = [
        ProductTemplate(name=f'Neighbor goods {n}', organization_id=bystander.id)
        for n, bystander in enumerate(bystanders)
    ]
    db.add(template)
    db.add_all(neighbor_templates)
    await db.flush()
    fixture.template_id = template.id

    await db.execute(
        _RECEIPTS_SQL,
        {
            'org_id': org.id,
            'template_id': template.id,
            'days': _DAYS_OF_HISTORY,
            'per_day': _RECEIPTS_PER_DAY,
            'unit_cost': _UNIT_COST,
            'foreign_currency': _FOREIGN_CURRENCY,
            'now': _NOW,
        },
    )
    await db.execute(
        _ISSUES_SQL,
        {
            'org_id': org.id,
            'template_id': template.id,
            'days': _DAYS_OF_HISTORY,
            'per_day': _ISSUES_PER_DAY,
            'unit_cost': _UNIT_COST,
            'now': _NOW,
        },
    )
    for n, bystander in enumerate(bystanders):
        await db.execute(
            _BYSTANDER_SQL,
            {
                'org_id': bystander.id,
                'template_id': neighbor_templates[n].id,
                'count': _BYSTANDER_LAYERS,
                'unit_cost': _UNIT_COST,
                'now': _NOW,
            },
        )
    await db.commit()

    # Planning off stale statistics is planning off a table Postgres thinks is
    # empty, which chooses a sequential scan whatever indexes exist.
    # The ANALYZE is deliberately left uncommitted: it holds the table's lock
    # until teardown, so an autovacuum that began before the seed landed —
    # carrying an empty picture of the table — cannot replace these statistics
    # between here and the read that plans on them.
    await db.execute(text('ANALYZE stock_valuation_layers'))

    included, foreign = _receipt_counts()
    fixture.total_layers = (
        _DAYS_OF_HISTORY * (_RECEIPTS_PER_DAY + _ISSUES_PER_DAY)
        + _BYSTANDERS * _BYSTANDER_LAYERS
    )
    fixture.receipts_before_the_date = included + foreign
    fixture.issues_before_the_date = _ISSUES_PER_DAY * (
        _DAYS_OF_HISTORY - _AS_OF_DAYS_AGO
    )
    fixture.foreign_before_the_date = foreign
    # Every receipt is one unit at one price, and an issue is the same unit
    # leaving, so what is left of the dated receipts is the receipts the
    # issues did not drain — whatever order the draw takes them in.
    fixture.expected_value = (
        Decimal(included - _ISSUES_PER_DAY * (_DAYS_OF_HISTORY - _AS_OF_DAYS_AGO))
        * _UNIT_COST
    )
    return fixture


async def _value_the_day(
    db: AsyncSession, fixture: _YearOfHistory
) -> tuple[dict[Any, Decimal], set[Any], int]:
    """The value per product, the products with a priced receipt, and the
    receipts a foreign currency left out — as the report reads them."""
    rows = (
        await db.execute(_values_as_of(fixture.org_id, _AS_OF, _ORG_CURRENCY))
    ).all()
    excluded = await _foreign_receipts_async(db, fixture.org_id, _AS_OF, _ORG_CURRENCY)
    return (
        {row.product_template_id: row.value for row in rows if row.value is not None},
        {row.product_template_id for row in rows if row.priced},
        excluded,
    )


def _nodes(plan: dict) -> Iterator[dict]:
    yield plan
    for child in plan.get('Plans', ()):
        yield from _nodes(child)


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


class TestTheDayIsReadFromAnIndex:
    async def test_the_plan_does_not_walk_the_whole_history(
        self, real_async_db_session: AsyncSession, year_of_history: _YearOfHistory
    ) -> None:
        db = real_async_db_session
        emitted: list[tuple[str, Any]] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            if 'stock_valuation_layers' in statement and 'ORDER BY' in statement:
                emitted.append((statement, parameters))

        engine = db.get_bind()
        event.listen(engine, 'before_cursor_execute', _capture)
        try:
            await _value_the_day(db, year_of_history)
        finally:
            event.remove(engine, 'before_cursor_execute', _capture)

        # The one statement that orders is the one that replays the
        # receipts; the refused count aggregates and has nothing to order.
        assert len(emitted) == 1, emitted
        await db.execute(text(_READ_BY_BITMAP))
        plan = await _plan_of(db, *emitted[0])
        await db.execute(text(_READ_IN_INDEX_ORDER_AGAIN))

        nodes = list(_nodes(plan))
        scans = [
            node
            for node in nodes
            if node.get('Relation Name') == 'stock_valuation_layers'
        ]
        assert scans, plan

        # The index answers the filter, so the layers the date excludes and
        # the layers of every other organization are never touched; the
        # pages it names are then read once each.
        assert not [node for node in scans if node['Node Type'] == 'Seq Scan'], plan
        assert [node['Node Type'] for node in scans] == ['Bitmap Heap Scan'] * len(
            scans
        ), plan
        assert [
            child.get('Index Name') for node in scans for child in node['Plans']
        ] == [_INDEX] * len(scans), plan

        # Read, not returned: the currency filter drops a few rows after the
        # index hands them over, and those rows were still read. The draw
        # reads the receipts and the issues up to the date, and nothing else.
        read = sum(
            node['Actual Rows']
            + node.get('Rows Removed by Filter', 0)
            + node.get('Rows Removed by Index Recheck', 0)
            for node in scans
        )
        assert read <= (
            year_of_history.receipts_before_the_date
            + year_of_history.issues_before_the_date
        ), plan
        assert read < year_of_history.total_layers // 2, plan

    async def test_the_report_reads_by_bitmap_and_hands_the_setting_back(
        self, real_async_db_session: AsyncSession, year_of_history: _YearOfHistory
    ) -> None:
        db = real_async_db_session
        emitted: list[str] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            emitted.append(statement)

        engine = db.get_bind()
        event.listen(engine, 'before_cursor_execute', _capture)
        try:
            await report_async(
                db,
                year_of_history.org_id,
                _AS_OF,
                org_currency=_ORG_CURRENCY,
                has_layers=True,
                limit=50,
            )
        finally:
            event.remove(engine, 'before_cursor_execute', _capture)

        (report,) = [
            n
            for n, statement in enumerate(emitted)
            if 'stock_valuation_layers' in statement and 'ORDER BY' in statement
        ]
        # The setting covers the report's statement and nothing after it: the
        # rest of the request plans as it always did.
        assert emitted[report - 1] == _READ_BY_BITMAP
        assert emitted[report + 1] == _READ_IN_INDEX_ORDER_AGAIN
        assert await db.scalar(text('SHOW enable_indexscan')) == 'on'


class TestTheDayIsWorthWhatTheLedgerSays:
    async def test_the_date_cuts_the_layers_it_should(
        self, real_async_db_session: AsyncSession, year_of_history: _YearOfHistory
    ) -> None:
        values, priced, excluded = await _value_the_day(
            real_async_db_session, year_of_history
        )

        # A product whose cost history reaches the date is priced; one whose
        # history does not is not worth a number at all.
        assert priced == {year_of_history.template_id}
        assert excluded == year_of_history.foreign_before_the_date
        assert values[year_of_history.template_id] == year_of_history.expected_value


class TestTheYearCostsAFixedNumberOfStatements:
    async def test_a_day_of_a_full_year_is_three_round_trips(
        self, real_async_db_session: AsyncSession, year_of_history: _YearOfHistory
    ) -> None:
        db = real_async_db_session
        emitted: list[str] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            emitted.append(statement)

        engine = db.get_bind()
        event.listen(engine, 'before_cursor_execute', _capture)
        try:
            await _value_the_day(db, year_of_history)
        finally:
            event.remove(engine, 'before_cursor_execute', _capture)

        assert len(emitted) == _STATEMENTS, emitted
