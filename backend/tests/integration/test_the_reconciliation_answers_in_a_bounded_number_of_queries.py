"""The reconciliation answers in a bounded number of queries.

The read-model compares pairs of sources, and the shape this pins
replaced one that carried the whole warehouse through Python: every
quant row hydrated to be added into a dictionary, and the item side
walked page by offset — each page re-reading the table from the top, so
an inventory of N items cost N²/1000 row visits, and the statement
count grew by one with every five hundred items on the shelf. A job
that runs by itself every six hours, for every organization, meets that
shape on the day the inventory outgrows the toy stage.

The bound is the pin: the whole read-model is a fixed handful of
statements, and seeding more items cannot push the count past it —
paging cannot hide inside a bound that does not move.

A bound on statements is not a bound on the answer, though: the sums were
once carried back as one row per group and compared in Python, so the memory
of a pass grew with the organization. The fixture below fills both sides of
every movement on purpose, and the second test pins that the comparison is
made in the database and one row comes back.

The records-against-quants pair, whose own numbers (and a poisoned NaN row
among them) were pinned here as well, ended with the quant table.
"""

from __future__ import annotations

import warnings
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services.analytics.reconciliation import get_reconciliation_async
from tests.integration._shelf import anchor_groups

#: Eleven hundred items — three pages at the old offset of five hundred,
#: which is three more statements than the shape being pinned allows.
_ITEM_COUNT = 1_100

#: One grouped query per source and one pass over the ledger. The old
#: shape's floor was nine and it grew with every page of items.
_QUERY_BOUND = 8

#: The ledger fixture: six locations, three templates, and a movement on
#: every ordered pair of locations — both sides filled, which is the shape
#: that made the one-sided fixture look harmless.
_LEDGER_LOCATIONS = 6
_LEDGER_TEMPLATES = 3


async def _organization(db: AsyncSession, label: str) -> Organization:
    org = Organization(
        name=f'{label} {uuid4().hex[:6]}',
        enabled_modules=['core', 'items'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _locations(
    db: AsyncSession, org: Organization, names: list[str]
) -> dict[str, StorageLocation]:
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'counted_{uuid4().hex[:8]}@test.com'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    locations = {}
    for name in names:
        location = StorageLocation(
            name=name,
            organization_id=org.id,
            storage_type_id=storage_type.id,
            created_by=user.id,
        )
        db.add(location)
        locations[name] = location
    await db.flush()
    return locations


async def _templates(
    db: AsyncSession, org: Organization, count: int
) -> list[ProductTemplate]:
    templates = [
        ProductTemplate(name=f'Counted product {n}', organization_id=org.id)
        for n in range(count)
    ]
    db.add_all(templates)
    await db.flush()
    return templates


@pytest.fixture
async def crowded_shelf(real_async_db_session: AsyncSession) -> UUID:
    """An organization whose inventory alone spans three old pages."""
    db = real_async_db_session

    org = await _organization(db, 'Counted')
    location = (await _locations(db, org, ['Aisle 1']))['Aisle 1']
    templates = await _templates(db, org, 5)

    # Five templates on one location: the grouped queries answer in a
    # handful of rows no matter how many items produced them.
    rows = [
        {
            'name': f'Item {n}',
            'organization_id': org.id,
            'storage_location_id': location.id,
            'template_id': templates[n % len(templates)].id,
            'quantity': Decimal('1.000'),
        }
        for n in range(_ITEM_COUNT)
    ]
    await db.run_sync(
        anchor_groups,
        [
            (r['organization_id'], r['template_id'], r['storage_location_id'])
            for r in rows
        ],
    )
    for start in range(0, len(rows), 2_000):
        await db.execute(insert(Item), rows[start : start + 2_000])
    await db.commit()
    return org.id


class TestTheAnswerArrivesInABoundedNumberOfQueries:
    async def test_a_full_shelf_is_not_carried_through_python(
        self, real_async_db_session: AsyncSession, crowded_shelf: UUID
    ) -> None:
        db = real_async_db_session
        statements: list[str] = []

        def _count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        engine = db.get_bind()
        event.listen(engine, 'before_cursor_execute', _count)
        try:
            dto = await get_reconciliation_async(db, crowded_shelf)
        finally:
            event.remove(engine, 'before_cursor_execute', _count)

        # The answer is still the answer: every seeded item was counted.
        assert dto.items_scanned == _ITEM_COUNT

        assert len(statements) <= _QUERY_BOUND, (
            f'{len(statements)} statements for {_ITEM_COUNT} items — paging '
            'or row-by-row hydration crept back into the read-model'
        )


@pytest.fixture
async def two_sided_ledger(real_async_db_session: AsyncSession) -> UUID:
    """A ledger where every movement has both locations filled.

    The fixture that came before this one gave each movement one empty
    side, and at that shape the number of ``(template, to, from)`` triples
    equals the number of ``(template, location)`` pairs — so the grouping
    key that produced the quadratic answer looked free.
    """
    db = real_async_db_session

    org = await _organization(db, 'Moved')
    locations = await _locations(
        db, org, [f'Dock {n}' for n in range(1, _LEDGER_LOCATIONS + 1)]
    )
    templates = await _templates(db, org, _LEDGER_TEMPLATES)
    names = list(locations)

    rows = []
    for template in templates:
        for origin in names:
            for destination in names:
                if origin == destination:
                    continue
                rows.append(
                    {
                        'organization_id': org.id,
                        'product_template_id': template.id,
                        'from_location_id': locations[origin].id,
                        'to_location_id': locations[destination].id,
                        'quantity': Decimal('1'),
                        'state': 'done',
                    }
                )
        # One receipt and one dispatch per template, so the netted pairs are
        # not all zero: a shape that lost the subtraction would still answer
        # in the same number of rows.
        rows.append(
            {
                'organization_id': org.id,
                'product_template_id': template.id,
                'from_location_id': None,
                'to_location_id': locations['Dock 1'].id,
                'quantity': Decimal('7'),
                'state': 'done',
            }
        )
        rows.append(
            {
                'organization_id': org.id,
                'product_template_id': template.id,
                'from_location_id': locations['Dock 2'].id,
                'to_location_id': None,
                'quantity': Decimal('3'),
                'state': 'done',
            }
        )
    await db.execute(insert(StockMove), rows)
    await db.commit()
    return org.id


class TestTheComparisonHappensInTheDatabase:
    async def test_no_statement_carries_a_group_per_pair_back_to_python(
        self, real_async_db_session: AsyncSession, two_sided_ledger: UUID
    ) -> None:
        db = real_async_db_session
        answered: list[int] = []

        def _count_rows(conn, cursor, statement, parameters, context, executemany):
            if 'stock_ledger_totals' in statement:
                answered.append(cursor.rowcount)

        engine = db.get_bind()
        event.listen(engine, 'after_cursor_execute', _count_rows)
        try:
            dto = await get_reconciliation_async(db, two_sided_ledger)
        finally:
            event.remove(engine, 'after_cursor_execute', _count_rows)

        # The ledger and the shelf are joined where they live, and one row of
        # ``(count, total)`` comes back — the old shape carried 42 groups
        # here, and 894 478 at 100 000 products.
        assert answered == [1], (
            f'the ledger statement answered in {answered} rows — the '
            'comparison is back in Python'
        )
        # And the netting is the same netting: five movements in and five
        # out for every dock, so only the receipt and the dispatch move
        # anything, and nothing is on the shelf to meet them.
        assert dto.quant_move_drift_count == 2 * _LEDGER_TEMPLATES
        assert dto.quant_move_drift_total == Decimal('30.000')


def _whole_ledger(organization_id: UUID):
    """The ledger's net as the reconciliation used to read it: every done movement.

    Kept here as the oracle the totals table is held against.
    """
    from sqlalchemy import func, select

    done = (
        StockMove.organization_id == organization_id,
        StockMove.state == 'done',
    )
    arrivals = select(
        StockMove.product_template_id.label('template_id'),
        StockMove.to_location_id.label('location_id'),
        StockMove.quantity.label('qty'),
    ).where(*done, StockMove.to_location_id.is_not(None))
    departures = select(
        StockMove.product_template_id,
        StockMove.from_location_id,
        -StockMove.quantity,
    ).where(*done, StockMove.from_location_id.is_not(None))
    stacked = arrivals.union_all(departures).subquery('stacked')
    return (
        select(
            stacked.c.template_id,
            stacked.c.location_id,
            func.sum(stacked.c.qty).label('total'),
        )
        .group_by(stacked.c.template_id, stacked.c.location_id)
        .cte('ledger')
    )


def _net_zero_history(org_id: UUID, template_id: UUID, location_id: UUID, n: int):
    """``n`` receipts to a shelf and ``n`` dispatches from it: history, no stock."""
    return [
        {
            'organization_id': org_id,
            'product_template_id': template_id,
            'from_location_id': location_id if side else None,
            'to_location_id': None if side else location_id,
            'quantity': Decimal('1'),
            'state': 'done',
        }
        for _ in range(n)
        for side in (0, 1)
    ]


async def _rows_read(db: AsyncSession, organization_id: UUID) -> dict[str, int]:
    """Rows each table gave the reconciliation's statements, from their plans.

    A scan's rows are the ones it returned and the ones its filter threw
    away: both were read.
    """
    import json

    statements: list[tuple[str, object]] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', _capture)
    try:
        await get_reconciliation_async(db, organization_id)
    finally:
        event.remove(engine, 'before_cursor_execute', _capture)
    await db.rollback()

    read: dict[str, int] = {}

    def _walk(node: dict) -> None:
        if 'Relation Name' in node:
            read[node['Relation Name']] = (
                read.get(node['Relation Name'], 0)
                + node['Actual Rows'] * node['Actual Loops']
                + node.get('Rows Removed by Filter', 0)
            )
        for child in node.get('Plans', []):
            _walk(child)

    connection = await db.connection()
    for statement, parameters in statements:
        if statement.startswith('SET LOCAL'):
            continue
        plan = (
            await connection.exec_driver_sql(
                'EXPLAIN (ANALYZE, FORMAT JSON) ' + statement, parameters
            )
        ).scalar()
        _walk((json.loads(plan) if isinstance(plan, str) else plan)[0]['Plan'])
    await db.rollback()
    return read


class TestTheLedgerHistoryIsNotRead:
    async def test_a_longer_history_costs_the_pass_no_more_rows(
        self, real_async_db_session: AsyncSession, two_sided_ledger: UUID
    ) -> None:
        """The pass reads the same rows after a thousand more movements.

        The reconciliation summed every done movement of the organization on
        every pass, and the ledger only grows. Movements that cancel out add
        history and no stock, so the answer cannot move, and neither may the
        cost of reaching it.
        """
        db = real_async_db_session
        before = await _rows_read(db, two_sided_ledger)
        template_id, location_id = (
            await db.execute(
                select(StockMove.product_template_id, StockMove.to_location_id)
                .where(
                    StockMove.organization_id == two_sided_ledger,
                    StockMove.to_location_id.is_not(None),
                )
                .limit(1)
            )
        ).one()
        await db.execute(
            insert(StockMove),
            _net_zero_history(two_sided_ledger, template_id, location_id, 500),
        )
        await db.commit()

        after = await _rows_read(db, two_sided_ledger)

        assert 'stock_moves' not in after, (
            f'the reconciliation read {after["stock_moves"]} movements'
        )
        assert after == before


class TestTheTotalsAnswerWhatTheWholeLedgerDid:
    async def test_the_answer_is_the_one_the_full_scan_gave(
        self,
        real_async_db_session: AsyncSession,
        two_sided_ledger: UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every way a movement is written, changed or taken away, then both readings.

        The movements are written in one statement and one at a time, one is
        corrected, one removed, and one product is deleted with its whole
        history; there is stock on the shelves for the pair to compare with.
        The totals must hold what adding up the ledger holds, and the answer
        must be the one the reconciliation gave when it added it up.
        """
        from sqlalchemy import delete, func, update

        from app.models.stock_ledger_total import StockLedgerTotal
        from app.services import stock_moves_service
        from app.services.analytics import reconciliation

        db = real_async_db_session
        org_id = two_sided_ledger
        moves = (
            await db.scalars(
                select(StockMove)
                .where(StockMove.organization_id == org_id)
                .order_by(StockMove.id)
            )
        ).all()
        kept, gone = moves[0], moves[1]
        templates = sorted({move.product_template_id for move in moves})
        location_id = kept.to_location_id or kept.from_location_id

        await stock_moves_service.create_async(
            db,
            organization_id=org_id,
            product_template_id=templates[0],
            to_location_id=location_id,
            quantity=Decimal('2.500'),
        )
        await db.execute(
            update(StockMove)
            .where(StockMove.id == kept.id)
            .values(quantity=kept.quantity + Decimal('4'))
        )
        await db.execute(delete(StockMove).where(StockMove.id == gone.id))
        await db.execute(
            delete(ProductTemplate).where(ProductTemplate.id == templates[-1])
        )
        shelf = [
            {
                'name': f'On the shelf {n}',
                'organization_id': org_id,
                'storage_location_id': location_id,
                'template_id': templates[n % 2],
                'quantity': Decimal('3.000'),
            }
            for n in range(4)
        ]
        await db.run_sync(
            anchor_groups,
            [
                (r['organization_id'], r['template_id'], r['storage_location_id'])
                for r in shelf
            ],
        )
        await db.execute(insert(Item), shelf)
        await db.commit()

        oracle = _whole_ledger(org_id)
        kept_totals = (
            await db.execute(
                select(
                    StockLedgerTotal.product_template_id,
                    StockLedgerTotal.storage_location_id,
                    StockLedgerTotal.quantity,
                ).where(StockLedgerTotal.organization_id == org_id)
            )
        ).all()
        summed = (
            await db.execute(
                select(oracle.c.template_id, oracle.c.location_id, oracle.c.total)
            )
        ).all()
        assert sorted(kept_totals) == sorted(summed)
        assert (
            await db.scalar(
                select(func.count())
                .select_from(StockLedgerTotal)
                .where(StockLedgerTotal.product_template_id == templates[-1])
            )
            == 0
        )

        answer = await get_reconciliation_async(db, org_id)
        await db.rollback()
        monkeypatch.setattr(reconciliation, '_ledger_totals', _whole_ledger)
        assert answer == await get_reconciliation_async(db, org_id)
        assert answer.quant_move_drift_count


class TestTheTwoPairsAreJoinedOnPurpose:
    async def test_the_statement_raises_no_cartesian_product_warning(
        self, real_async_db_session: AsyncSession, two_sided_ledger: UUID
    ) -> None:
        db = real_async_db_session
        # SQLAlchemy lints a statement when it compiles it, and a compiled
        # statement is cached: start from an empty cache so this run compiles.
        db.get_bind().clear_compiled_cache()

        with warnings.catch_warnings():
            warnings.simplefilter('error', sa_exc.SAWarning)
            await get_reconciliation_async(db, two_sided_ledger)
