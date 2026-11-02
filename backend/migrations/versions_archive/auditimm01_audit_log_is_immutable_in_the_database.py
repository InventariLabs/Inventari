"""Restore the audit_log immutability trigger, which the squash ate

The model's docstring, ``core/public_api/audit_log.py`` and the tests all say
audit entries are made immutable by a database trigger. That trigger was
created by a migration that now lives in ``versions_archive/``; the squashed
baseline creates the table without it, and no migration in the live chain
issues a ``CREATE TRIGGER`` at all. On a database migrated from the baseline —
which is every installation created since 2026-06-10 — ``pg_trigger`` for
``audit_log`` is empty, and any client with write access can ``UPDATE`` or
``DELETE`` a log entry.

A guarantee documented in three places and enforced in none is worse than no
guarantee: it is what stops anyone from looking.

Idempotent on purpose (``CREATE OR REPLACE`` + ``DROP TRIGGER IF EXISTS``), so
it is safe on a database that already carries the trigger from the pre-squash
chain.

Revision ID: auditimm01
Revises: dropppu01
"""

from alembic import op

revision = 'auditimm01'
down_revision = 'dropppu01'
branch_labels = None
depends_on = None

# Kept here rather than imported from the model: a migration is a snapshot of
# what was done, and one that reads today's application code says something
# different tomorrow. The guard against this drifting apart again is a test
# that reads the migration chain, not a shared constant.
TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION audit_log_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log rows are immutable: % operation not allowed', TG_OP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
"""


def upgrade() -> None:
    op.execute(TRIGGER_SQL)


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log')
    op.execute('DROP FUNCTION IF EXISTS audit_log_immutable()')
