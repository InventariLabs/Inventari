"""The audit log's immutability is enforced by the database, or it is a story.

Three places said a trigger made audit entries append-only: the model's
docstring, `core/public_api/audit_log.py`, and the tests that quote it. The
trigger was created by a migration that now sits in `versions_archive/`. The
squashed baseline creates the table without it, no migration in the live chain
issues a `CREATE TRIGGER` at all, and `pg_trigger` for `audit_log` on a
database migrated from that baseline was empty — so since 2026-06-10, anyone
with write access could rewrite or erase a log entry, and every document
saying otherwise made that less likely to be noticed.

Two tests, because there are two ways to lose this:

- the trigger stops working, which the behaviour test catches;
- the trigger falls out of the migration chain, which only reading the chain
  catches. That is exactly how it was lost, and how seven trigram indexes were
  lost before it, and CI stayed green through both.
"""

import importlib
import pathlib
import re
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization

pytestmark = pytest.mark.integration

_migration = importlib.import_module('migrations.versions.baseline_002_full_schema')
VERSIONS = pathlib.Path(__file__).resolve().parents[2] / 'migrations' / 'versions'


@pytest.fixture
def audited_row(
    db_session: Session, test_household: Organization
) -> Generator[AuditLog]:
    """One entry, plus the trigger — and the trigger goes away again.

    The test databases are built with `create_all`, which knows about tables
    and nothing about triggers — the same blind spot the squash had. So the
    migration's own SQL is run here, which also means this test exercises the
    statement that ships rather than a copy of it.

    Dropping it afterwards is not tidiness. A trigger is DDL: it outlives the
    transaction and stays on this xdist worker's database for every test that
    follows. That was invisible while the suite emptied tables with TRUNCATE,
    which does not fire row triggers; the moment teardown deletes rows
    instead, one test leaves a database where nothing can clear `audit_log`
    and the next hundred fail somewhere else entirely.
    """
    db_session.execute(text(_migration.TRIGGER_SQL))
    entry = AuditLog(
        organization_id=test_household.id,
        action='CREATE',
        target_type='item',
        target_id=uuid.uuid4(),
        reason='as recorded',
    )
    db_session.add(entry)
    db_session.commit()
    yield entry
    db_session.rollback()
    db_session.execute(text('DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log'))
    db_session.execute(text('DROP FUNCTION IF EXISTS audit_log_immutable()'))
    db_session.commit()


def test_a_recorded_entry_cannot_be_rewritten(
    db_session: Session, audited_row: AuditLog
) -> None:
    with pytest.raises(DatabaseError, match='immutable'):
        db_session.execute(
            text('UPDATE audit_log SET reason = :r WHERE id = :i'),
            {'r': 'not what happened', 'i': audited_row.id},
        )
    db_session.rollback()


def test_a_recorded_entry_cannot_be_erased(
    db_session: Session, audited_row: AuditLog
) -> None:
    with pytest.raises(DatabaseError, match='immutable'):
        db_session.execute(
            text('DELETE FROM audit_log WHERE id = :i'), {'i': audited_row.id}
        )
    db_session.rollback()


def test_the_migration_chain_still_creates_the_trigger() -> None:
    """Reading the chain, because that is where it went missing.

    A squash that rebuilds the baseline from `Base.metadata` produces every
    table and no trigger, and nothing else in the suite would notice: the test
    above runs the SQL itself, so it would keep passing over a chain that no
    longer carries it.
    """
    chain = '\n'.join(
        path.read_text(encoding='utf-8') for path in VERSIONS.glob('*.py')
    )
    assert re.search(r'CREATE\s+TRIGGER\s+audit_log_immutable', chain), (
        'no migration in versions/ creates the audit_log_immutable trigger'
    )
