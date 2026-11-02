"""The organization journal with a hundred thousand entries in it.

The journal is append-only by a database trigger and nothing prunes it, so
whatever a read of it costs, an established instance pays on a bigger table
every year. Three reads of it grew with the table when they did not have to:

- the page deep in the journal, which paged with ``OFFSET`` and so produced
  every entry above it to throw them away;
- the list of target types the screen's filter offers, which read every entry
  of the organization on each visit to find a handful of values;
- the journal narrowed to one kind of thing, whose page and count had no index
  to start from and read the organization's timeline until they found enough.

What is measured is the work the database reports for the statements the
service actually sends — the rows it read from the journal and, for the list
of types, the buffers it touched — and not a clock, which measures the machine
(see ``test_the_ledger_stays_quick_when_it_is_long.py`` for how that went). The
buffers of a page that reads table rows are not the measure: how many pages the
same rows sit on depends on how the table was filled, and an index scan pays a
buffer for every entry whose row an earlier test deleted and no vacuum has yet
removed (``_entries_deleted_before``). Rows read count only live rows.

A hundred thousand entries, five to an instant, so a page boundary cuts
through a group that shares its date. Nearly all of them are one kind of
thing, a few hundred are another, and ten of a third kind sit at the oldest
end of the journal: the sparse case, which is the hard one for an index that
only carries the sort order.
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
from app.services import audit_service

_JOURNAL_SIZE = 100_000
_PAGE = 100
_TIES = 5
_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
_RARE_ENTRIES = 10
_COMMON_TYPE = 'item'
_SOME_TYPE = 'storage_location'
_RARE_TYPE = 'equipment_model'

#: Rows the database may read from the journal to produce one page: the page,
#: the entries that share the instant it starts at, and no more.
_ROWS_PER_PAGE = _PAGE + 2 * _TIES

#: The list of types reads an index entry or two per type; a read of every
#: entry of the organization's journal is thousands of buffers.
_TYPES_BUFFER_BUDGET = 60


class _Journal:
    def __init__(self) -> None:
        self.org_id: UUID


@pytest.fixture
async def long_journal(real_async_db_session: AsyncSession) -> _Journal:
    db = real_async_db_session
    journal = _Journal()
    org = Organization(
        name=f'Journal {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    journal.org_id = org.id
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'journal_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    # Generated in the database: sending a hundred thousand rows through the
    # driver would make the fixture the slow part of the file.
    await db.execute(
        text(
            """
            INSERT INTO audit_log (
                id, organization_id, user_id, action, target_type, target_id,
                created_at
            )
            SELECT
                gen_random_uuid(), :org, :user, 'UPDATE',
                CASE
                    WHEN n >= :rare_from THEN :rare_type
                    WHEN n % 250 = 7 THEN :some_type
                    ELSE :common_type
                END,
                gen_random_uuid(),
                CAST(:now AS timestamptz)
                    - (n / CAST(:ties AS integer)) * interval '1 minute'
            FROM generate_series(0, CAST(:last AS integer)) AS n
            """
        ),
        {
            'org': org.id,
            'user': user.id,
            'now': _NOW,
            'ties': _TIES,
            'last': _JOURNAL_SIZE - 1,
            'rare_from': _JOURNAL_SIZE - _RARE_ENTRIES,
            'rare_type': _RARE_TYPE,
            'some_type': _SOME_TYPE,
            'common_type': _COMMON_TYPE,
        },
    )
    await db.commit()
    await _other_tenants(db)
    # Left uncommitted on purpose, as in the ledger's files: the lock keeps an
    # autovacuum that began before the seed from replacing these statistics
    # with an empty picture of the table.
    await db.execute(text('ANALYZE audit_log'))
    return journal


#: A different journal: a hundred thousand entries of which fifty thousand
#: share ONE instant — an import, a bulk edit — with ordinary history above and
#: below. A group that size is not bounded by the page, and a page that starts
#: inside it is the case a seek on the date alone handles badly.
_BULK_FROM = 30_000
_BULK_TO = 80_000


@pytest.fixture
async def bulk_journal(real_async_db_session: AsyncSession) -> _Journal:
    db = real_async_db_session
    journal = _Journal()
    org = Organization(
        name=f'Bulk journal {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    journal.org_id = org.id
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'bulkj_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    await db.execute(
        text(
            """
            INSERT INTO audit_log (
                id, organization_id, user_id, action, target_type, target_id,
                created_at
            )
            SELECT
                gen_random_uuid(), :org, :user, 'UPDATE', 'item',
                gen_random_uuid(),
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
                END
            FROM generate_series(0, CAST(:last AS integer)) AS n
            """
        ),
        {
            'org': org.id,
            'user': user.id,
            'now': _NOW,
            'ties': _TIES,
            'last': _JOURNAL_SIZE - 1,
            'bulk_from': _BULK_FROM,
            'bulk_to': _BULK_TO,
        },
    )
    await db.commit()
    await _other_tenants(db)
    await db.execute(text('ANALYZE audit_log'))
    return journal


_NOISE_ORGS = 3
_NOISE_ENTRIES = 100_000
#: Sorts after every type the journals below use, so an index that starts at the
#: type and not at the organization must walk all of it to get past.
_NOISE_TYPE = 'zz_other_tenants'


async def _other_tenants(db: AsyncSession) -> None:
    """A shared table: other organizations' entries, as many as this one's.

    The journal is one table for every organization, and an index that starts
    at the type reads the other tenants' rows to find this one's. A table that
    holds nothing but the organization under test cannot show that, and then
    the planner has no reason to prefer the index built for the purpose.
    """
    orgs = [
        Organization(name=f'Neighbour {i} {uuid4().hex[:6]}', enabled_modules=['core'])
        for i in range(_NOISE_ORGS)
    ]
    db.add_all(orgs)
    await db.commit()
    for org in orgs:
        await db.refresh(org)
    await db.execute(
        text(
            """
            INSERT INTO audit_log (
                id, organization_id, action, target_type, target_id, created_at
            )
            SELECT
                gen_random_uuid(),
                (CAST(:orgs AS uuid[]))[1 + n % CAST(:count AS integer)],
                'UPDATE', :kind, gen_random_uuid(),
                CAST(:now AS timestamptz) - (n % 50000) * interval '1 minute'
            FROM generate_series(0, CAST(:last AS integer)) AS n
            """
        ),
        {
            'orgs': [org.id for org in orgs],
            'count': _NOISE_ORGS,
            'kind': _NOISE_TYPE,
            'now': _NOW,
            'last': _NOISE_ENTRIES - 1,
        },
    )
    await db.commit()


#: Deleted entries of the rare kind the page's index still points at.
_DELETED_RARE_ENTRIES = 200


async def _entries_deleted_before(db: AsyncSession, org_id: UUID, kind: str) -> None:
    """Entries of *kind* deleted while this test's transaction is open.

    The test database is cleared between tests by deleting rows, so the index
    an earlier test filled on the same worker still points at them until a
    vacuum runs — and no vacuum may remove a row that an open transaction,
    this test's own or an autovacuum's, could still see. An index scan visits
    each such row in the table to find it dead, and that visit is a buffer.
    Which state a test meets depended on what ran before it on its worker and
    on when autovacuum got there; here it meets the worst one every time.
    """
    async with db.bind.connect() as other:
        await other.execute(
            text(
                """
                INSERT INTO audit_log (
                    id, organization_id, action, target_type, target_id, created_at
                )
                SELECT gen_random_uuid(), :org, 'UPDATE', :kind,
                       gen_random_uuid(), CAST(:now AS timestamptz)
                FROM generate_series(1, CAST(:count AS integer))
                """
            ),
            {'org': org_id, 'kind': kind, 'now': _NOW, 'count': _DELETED_RARE_ENTRIES},
        )
        await other.commit()
        await other.execute(
            text(
                'DELETE FROM audit_log WHERE organization_id = :org '
                'AND target_type = :kind AND created_at = CAST(:now AS timestamptz)'
            ),
            {'org': org_id, 'kind': kind, 'now': _NOW},
        )
        await other.commit()


def _nodes(plan: dict) -> list[dict]:
    found = [plan]
    for child in plan.get('Plans', []):
        found.extend(_nodes(child))
    return found


def _buffers(plan: dict) -> int:
    return plan.get('Shared Hit Blocks', 0) + plan.get('Shared Read Blocks', 0)


def _rows_read(plans: list[dict]) -> int:
    """Rows the statements read from the journal itself, kept or thrown away."""
    return sum(
        (node.get('Actual Rows', 0) + node.get('Rows Removed by Filter', 0))
        * node.get('Actual Loops', 1)
        for plan in plans
        for node in _nodes(plan)
        if node.get('Relation Name') == 'audit_log'
    )


def _audit_scans(plan: dict) -> set[str]:
    return {
        node['Node Type']
        for node in _nodes(plan)
        if node.get('Relation Name') == 'audit_log'
    }


def _indexes(plan: dict) -> set[str | None]:
    return {node.get('Index Name') for node in _nodes(plan)}


async def _explained_all(
    db: AsyncSession, call, wanted, *, most: int = 1
) -> tuple[object, list[dict]]:
    """Run *call*, then ``EXPLAIN (ANALYZE, BUFFERS)`` the statements *wanted* picks.

    A page that starts inside a group of entries sharing one instant is read in
    two steps (the rest of the group, then the older entries), so a page may
    be up to *most* statements; what it costs is what they cost together.
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

    chosen = [(s, p) for s, p in sent if wanted(s)]
    assert 1 <= len(chosen) <= most, [statement for statement, _ in sent]
    connection = await db.connection()
    plans = []
    for statement, parameters in chosen:
        explained = await connection.exec_driver_sql(
            f'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}', parameters
        )
        plans.append(explained.scalar()[0]['Plan'])
    return result, plans


async def _explained(db: AsyncSession, call, wanted) -> tuple[object, dict]:
    """The one statement *wanted* picks, explained."""
    result, plans = await _explained_all(db, call, wanted)
    return result, plans[0]


def _is_the_page(statement: str) -> bool:
    return 'ORDER BY' in statement and 'FROM audit_log' in statement


def _is_the_count(statement: str) -> bool:
    return 'count(' in statement.lower() and 'FROM audit_log' in statement


def _is_the_types(statement: str) -> bool:
    return 'RECURSIVE' in statement.upper()


async def _ids_after(
    db: AsyncSession, org_id: UUID, position: int, limit: int
) -> list[UUID]:
    """The ids that follow *position* in the journal's order, by the plain definition."""
    rows = await db.execute(
        text(
            """
            SELECT id FROM audit_log
            WHERE organization_id = :org
            ORDER BY created_at DESC, id
            OFFSET :start LIMIT :limit
            """
        ),
        {'org': org_id, 'start': position + 1, 'limit': limit},
    )
    return [row.id for row in rows]


async def _row_at(
    db: AsyncSession, org_id: UUID, position: int
) -> tuple[datetime, UUID]:
    row = (
        await db.execute(
            text(
                """
                SELECT created_at, id FROM audit_log
                WHERE organization_id = :org
                ORDER BY created_at DESC, id
                OFFSET :position LIMIT 1
                """
            ),
            {'org': org_id, 'position': position},
        )
    ).one()
    return row.created_at, row.id


@pytest.mark.integration
class TestADeepPageIsASeek:
    async def test_the_page_near_the_end_reads_the_rows_the_first_page_reads(
        self, real_async_db_session: AsyncSession, long_journal: _Journal
    ) -> None:
        db = real_async_db_session
        (_, total), first = await _explained_all(
            db,
            lambda: audit_service.list_for_org_async(
                db, long_journal.org_id, limit=_PAGE
            ),
            _is_the_page,
            most=2,
        )
        after_created_at, after_id = await _row_at(
            db, long_journal.org_id, _JOURNAL_SIZE - _PAGE - 1
        )
        (rows, deep_total), deep = await _explained_all(
            db,
            lambda: audit_service.list_for_org_async(
                db,
                long_journal.org_id,
                limit=_PAGE,
                after=(after_created_at, after_id),
                known_total=total,
            ),
            _is_the_page,
            most=2,
        )

        assert total == _JOURNAL_SIZE
        assert deep_total == _JOURNAL_SIZE
        assert [entry.id for entry, _ in rows] == await _ids_after(
            db, long_journal.org_id, _JOURNAL_SIZE - _PAGE - 1, _PAGE
        )
        assert _rows_read(first) <= _ROWS_PER_PAGE, _rows_read(first)
        assert _rows_read(deep) <= _ROWS_PER_PAGE, (
            _rows_read(first),
            _rows_read(deep),
        )

    async def test_the_offset_page_it_replaces_reads_the_journal_above_it(
        self, real_async_db_session: AsyncSession, long_journal: _Journal
    ) -> None:
        """The contrast the test above stands on, so it cannot pass by default."""
        db = real_async_db_session
        _, first = await _explained_all(
            db,
            lambda: audit_service.list_for_org_async(
                db, long_journal.org_id, limit=_PAGE, known_total=_JOURNAL_SIZE
            ),
            _is_the_page,
            most=2,
        )
        _, by_offset = await _explained_all(
            db,
            lambda: audit_service.list_for_org_async(
                db,
                long_journal.org_id,
                limit=_PAGE,
                offset=_JOURNAL_SIZE - _PAGE,
                known_total=_JOURNAL_SIZE,
            ),
            _is_the_page,
            most=2,
        )

        assert _rows_read(by_offset) > 50 * _rows_read(first), (
            _rows_read(first),
            _rows_read(by_offset),
        )


@pytest.mark.integration
class TestTheListOfTypesIsALooseScan:
    async def test_it_names_the_types_and_reads_an_entry_or_two_of_each(
        self, real_async_db_session: AsyncSession, long_journal: _Journal
    ) -> None:
        db = real_async_db_session
        types, plan = await _explained(
            db,
            lambda: audit_service.list_target_types_async(db, long_journal.org_id),
            _is_the_types,
        )

        assert types == sorted([_COMMON_TYPE, _SOME_TYPE, _RARE_TYPE])
        assert 'Seq Scan' not in _audit_scans(plan), _audit_scans(plan)
        assert 'ix_audit_log_org_type_created_at' in _indexes(plan), _indexes(plan)
        assert _buffers(plan) <= _TYPES_BUFFER_BUDGET, _buffers(plan)

    async def test_distinct_over_the_journal_reads_far_more(
        self, real_async_db_session: AsyncSession, long_journal: _Journal
    ) -> None:
        """What the loose scan replaces, so the budget above means something."""
        db = real_async_db_session
        connection = await db.connection()
        explained = await connection.exec_driver_sql(
            'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '
            'SELECT DISTINCT target_type FROM audit_log '
            f"WHERE organization_id = '{long_journal.org_id}' ORDER BY target_type"
        )
        distinct = explained.scalar()[0]['Plan']

        assert _buffers(distinct) > 10 * _TYPES_BUFFER_BUDGET, _buffers(distinct)


@pytest.mark.integration
class TestTheJournalNarrowedToOneKind:
    async def test_the_count_is_read_off_the_index_not_the_table(
        self, real_async_db_session: AsyncSession, long_journal: _Journal
    ) -> None:
        db = real_async_db_session
        (rows, total), plan = await _explained(
            db,
            lambda: audit_service.list_for_org_async(
                db, long_journal.org_id, target_type=_SOME_TYPE, limit=_PAGE
            ),
            _is_the_count,
        )

        assert total == _JOURNAL_SIZE // 250
        assert len(rows) == _PAGE or len(rows) == total
        # Either index that starts at the type reads 400 entries; what the
        # count must not do is read the table, which is what it did.
        assert 'Seq Scan' not in _audit_scans(plan), _audit_scans(plan)

    async def test_the_page_of_a_rare_kind_does_not_walk_the_timeline(
        self, real_async_db_session: AsyncSession, long_journal: _Journal
    ) -> None:
        """Ten entries at the oldest end of a hundred thousand.

        Through the organization's timeline index they sit behind every other
        entry, and the page reads the lot to find them. Through the index that
        starts at the type they are the first ten it meets.
        """
        db = real_async_db_session
        await _entries_deleted_before(db, long_journal.org_id, _RARE_TYPE)
        (rows, total), plan = await _explained(
            db,
            lambda: audit_service.list_for_org_async(
                db, long_journal.org_id, target_type=_RARE_TYPE, limit=_PAGE
            ),
            _is_the_page,
        )

        assert total == _RARE_ENTRIES
        assert len(rows) == _RARE_ENTRIES
        # Which index finds them is the planner's to choose; what it must not
        # do is read the timeline above them, which is a hundred thousand rows.
        # The buffers are not bounded: the deleted entries above cost one
        # each, however the rows are found.
        assert _rows_read([plan]) <= _PAGE, _rows_read([plan])


@pytest.mark.integration
class TestAPageInsideALargeGroupOfTiedEntries:
    async def test_every_such_page_is_the_right_entries_read_at_the_price_of_a_page(
        self, real_async_db_session: AsyncSession, bulk_journal: _Journal
    ) -> None:
        """Fifty thousand entries share an instant; the pages through it are flat.

        The positions are the ones where the cost differs: just before the
        group, in its first entries, in its middle (where a condition that
        cannot start inside the group reads half of it), at its end, one page
        that leaves it for older history, and deep in that history. Each is
        checked for the entries it returns — the exact ids the plain
        definition of the order gives — and for the rows it read to get them,
        against the same budget as a page in a journal with no large group.
        """
        db = real_async_db_session
        positions = [
            _BULK_FROM - 10,
            _BULK_FROM,
            _BULK_FROM + 1,
            (_BULK_FROM + _BULK_TO) // 2,
            _BULK_TO - _PAGE // 2,
            _BULK_TO - 1,
            _JOURNAL_SIZE - _PAGE - 1,
        ]
        for position in positions:
            after = await _row_at(db, bulk_journal.org_id, position)

            (rows, total), plans = await _explained_all(
                db,
                partial(
                    audit_service.list_for_org_async,
                    db,
                    bulk_journal.org_id,
                    limit=_PAGE,
                    after=after,
                    known_total=_JOURNAL_SIZE,
                ),
                _is_the_page,
                most=2,
            )

            assert [entry.id for entry, _ in rows] == await _ids_after(
                db, bulk_journal.org_id, position, _PAGE
            ), position
            assert total == _JOURNAL_SIZE
            assert _rows_read(plans) <= _ROWS_PER_PAGE, (position, _rows_read(plans))

    async def test_the_same_inside_the_group_when_narrowed_to_a_type(
        self, real_async_db_session: AsyncSession, bulk_journal: _Journal
    ) -> None:
        """The journal narrowed to one kind of thing reads the group through its own index."""
        db = real_async_db_session
        position = (_BULK_FROM + _BULK_TO) // 2
        after = await _row_at(db, bulk_journal.org_id, position)

        (rows, total), plans = await _explained_all(
            db,
            partial(
                audit_service.list_for_org_async,
                db,
                bulk_journal.org_id,
                target_type=_COMMON_TYPE,
                limit=_PAGE,
                after=after,
                known_total=_JOURNAL_SIZE,
            ),
            _is_the_page,
            most=2,
        )

        assert [entry.id for entry, _ in rows] == await _ids_after(
            db, bulk_journal.org_id, position, _PAGE
        )
        assert total == _JOURNAL_SIZE
        assert _rows_read(plans) <= _ROWS_PER_PAGE, _rows_read(plans)


class TestTheJournalCarriesNoIndexThatInvitesTheWrongPlan:
    def test_no_index_serves_the_date_alone(self) -> None:
        """A page of older entries must not be plannable on the date by itself.

        ``organization_id = ?`` is a constant of the query, so it cannot be put
        in the ``ORDER BY`` to rule out an index on ``created_at`` alone. Where
        that index exists the planner may, depending on its sample, walk it
        backward and filter out the other tenants' entries one by one. The
        absence of the index is the only thing that makes the plan impossible,
        so this does not depend on the planner's statistics.
        """
        from app.models.audit_log import AuditLog

        leading = {
            tuple(column.name for column in index.columns)[:1]
            for index in AuditLog.__table__.indexes
        }
        assert ('created_at',) not in leading
