"""The organization journal with ten thousand entries in it.

Every meaningful action the platform takes lands in the journal, and
nothing prunes it — the point of an audit trail is that it keeps
everything, and the database trigger makes sure of it. A journal a year
old is the norm, not the stress case.

The page query is ``WHERE organization_id = ? ORDER BY created_at DESC
OFFSET ? LIMIT ?`` with a ``COUNT(*)`` of the same filter on every page.
Both single-column indexes fail that pair: the planner either reads the
organization and sorts it in memory, or walks the whole timeline past
every other organization's rows to hand back one page.

What is explained is the statement the service sends, captured as it
leaves for the driver — not a copy of it written out here, which would
stay green however the service's ORDER BY or JOIN changed. The plan check
fails the moment the page stops being read off ``ix_audit_log_org_created_at_id``,
at any table size: without that index the planner does not sort, it walks
the whole timeline backwards past every other organization's rows, so the
index name in the plan is what discriminates; the absence of a "Sort" node
only guards the other way to lose it. There is no clock: the ledger's
file dropped its one for being red on a loaded host, and a plan does not
depend on who else is using the machine.

Note the measurement is of reads only. The development stack runs with
``fsync=off``, so the seeding time in this file means nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.services import audit_service

#: Ten thousand entries is roughly a year of a busy organization: every
#: receipt, pick, recipe change and role touch, recorded.
_JOURNAL_SIZE = 10_000

#: One page as the screen asks for it.
_PAGE = 50

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

#: One page read is the count and the page.
_STATEMENTS = 2


class _BusyOrganization:
    def __init__(self) -> None:
        self.org_id: UUID
        self.user_id: UUID


@pytest.fixture
async def busy_organization(
    real_async_db_session: AsyncSession,
) -> _BusyOrganization:
    """Ten thousand entries for one organization, and two bystanders whose
    entries interleave with them on the same timeline.

    The bystanders are what makes the plan honest. A table holding only the
    one organization's rows makes the timeline index look perfect — every
    row the backward scan touches belongs to the reader anyway, which is
    exactly the shape no real instance has. With bystanders interleaved,
    walking the timeline means reading past foreign rows on every page,
    and the composite index is what the planner prefers.
    """
    db = real_async_db_session
    fixture = _BusyOrganization()

    org = Organization(
        name=f'Journaling {uuid4().hex[:6]}',
        enabled_modules=['core'],
    )
    bystanders = [
        Organization(
            name=f'Journal bystander {n} {uuid4().hex[:6]}',
            enabled_modules=['core'],
        )
        for n in range(2)
    ]
    db.add(org)
    db.add_all(bystanders)
    await db.commit()
    await db.refresh(org)
    fixture.org_id = org.id

    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'journal_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    fixture.user_id = user.id

    def _entry(org_row: Organization, n: int) -> dict:
        return {
            'id': uuid4(),
            'organization_id': org_row.id,
            'user_id': user.id if n % 3 else None,
            'action': 'UPDATE',
            'target_type': 'item',
            'target_id': uuid4(),
            'reason': f'Journal entry {n}',
            'created_at': _NOW - timedelta(minutes=n),
        }

    rows = [_entry(org, n) for n in range(_JOURNAL_SIZE)]
    # Same timeline, half the volume: every second minute belongs to a
    # bystander too, so half of a timeline walk is somebody else's rows.
    rows.extend(_entry(bystanders[0], n) for n in range(0, _JOURNAL_SIZE, 2))
    rows.extend(_entry(bystanders[1], n) for n in range(0, _JOURNAL_SIZE, 2))
    for start in range(0, len(rows), 2_000):
        await db.execute(insert(AuditLog), rows[start : start + 2_000])
    await db.commit()

    # Planning off stale statistics is planning off a table Postgres thinks is
    # empty, which chooses a sequential scan whatever indexes exist.
    # The ANALYZE is deliberately left uncommitted: it holds the table's lock
    # until teardown, so an autovacuum that began before the seed landed —
    # carrying an empty picture of the table — cannot replace these statistics
    # between here and the read that plans on them.
    await db.execute(text('ANALYZE audit_log'))
    return fixture


def _nodes(plan: dict) -> list[dict]:
    found = [plan]
    for child in plan.get('Plans', []):
        found.extend(_nodes(child))
    return found


async def _read(db: AsyncSession, call) -> tuple[object, list[str], dict]:
    """Run *call*; return its result, the statements it sent, and the page plan.

    The plan is asked for after the call, on the statement as the driver
    received it, with its own parameters.
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
    pages = [
        (statement, parameters)
        for statement, parameters in sent
        if 'ORDER BY' in statement and 'FROM audit_log' in statement
    ]
    assert len(pages) == 1, [statement for statement, _ in sent]
    explained = await connection.exec_driver_sql(
        f'EXPLAIN (FORMAT JSON) {pages[0][0]}', pages[0][1]
    )
    return result, [statement for statement, _ in sent], explained.scalar()[0]['Plan']


def _assert_served_by_the_ordering_index(plan: dict, *, either_timeline: bool = False):
    """The page is read in journal order off an index, never sorted after a read.

    With a narrowing filter (a date range, a target type that matches most of
    the organization) the planner may rightly walk the plain timeline index
    instead of the composite one, and which it picks depends on what other
    tests left in the table. ``either_timeline`` accepts that; the sort and the
    sequential scan stay forbidden.
    """
    nodes = _nodes(plan)
    node_types = {node['Node Type'] for node in nodes}
    indexes = {node.get('Index Name') for node in nodes}
    assert not node_types & {'Sort', 'Incremental Sort'}, node_types
    if either_timeline:
        assert not any(
            node['Node Type'] == 'Seq Scan' and node.get('Relation Name') == 'audit_log'
            for node in nodes
        ), node_types
        assert indexes & {
            'ix_audit_log_org_created_at_id',
            'ix_audit_log_org_type_created_at',
            'ix_audit_log_created_at',
        }
    else:
        assert 'ix_audit_log_org_created_at_id' in indexes, indexes


class TestTheJournalPageIsServedByAnIndex:
    async def test_the_first_page_of_the_whole_journal(
        self, real_async_db_session: AsyncSession, busy_organization: _BusyOrganization
    ) -> None:
        (rows, total), statements, plan = await _read(
            real_async_db_session,
            lambda: audit_service.list_for_org_async(
                real_async_db_session,
                busy_organization.org_id,
                limit=_PAGE,
                offset=_PAGE,
            ),
        )

        assert total == _JOURNAL_SIZE
        assert len(rows) == _PAGE
        assert len(statements) == _STATEMENTS, statements
        _assert_served_by_the_ordering_index(plan)

    async def test_the_page_filtered_by_a_person(
        self, real_async_db_session: AsyncSession, busy_organization: _BusyOrganization
    ) -> None:
        (rows, total), statements, plan = await _read(
            real_async_db_session,
            lambda: audit_service.list_for_org_async(
                real_async_db_session,
                busy_organization.org_id,
                user_id=busy_organization.user_id,
                limit=_PAGE,
            ),
        )

        assert 0 < total < _JOURNAL_SIZE
        assert len(rows) == _PAGE
        assert len(statements) == _STATEMENTS, statements
        assert [email for _, email in rows] == [rows[0][1]] * _PAGE
        _assert_served_by_the_ordering_index(plan)

    async def test_the_page_filtered_by_a_date_range(
        self, real_async_db_session: AsyncSession, busy_organization: _BusyOrganization
    ) -> None:
        (rows, total), statements, plan = await _read(
            real_async_db_session,
            lambda: audit_service.list_for_org_async(
                real_async_db_session,
                busy_organization.org_id,
                since=_NOW - timedelta(minutes=5_000),
                until=_NOW - timedelta(minutes=100),
                limit=_PAGE,
            ),
        )

        assert total == 4_901
        assert len(rows) == _PAGE
        assert len(statements) == _STATEMENTS, statements
        _assert_served_by_the_ordering_index(plan, either_timeline=True)
        created = [entry.created_at for entry, _ in rows]
        assert created == sorted(created, reverse=True)

    async def test_the_page_filtered_by_what_was_touched(
        self, real_async_db_session: AsyncSession, busy_organization: _BusyOrganization
    ) -> None:
        (rows, total), statements, plan = await _read(
            real_async_db_session,
            lambda: audit_service.list_for_org_async(
                real_async_db_session,
                busy_organization.org_id,
                target_type='item',
                limit=_PAGE,
            ),
        )

        assert total == _JOURNAL_SIZE
        assert len(rows) == _PAGE
        assert len(statements) == _STATEMENTS, statements
        _assert_served_by_the_ordering_index(plan, either_timeline=True)
