"""index the organization journal on its own sort order

Revision ID: auditidx01
Revises: priceprec01
Create Date: 2026-09-09

The journal page asks for one organization newest-first
(``WHERE organization_id = ? ORDER BY created_at DESC OFFSET ? LIMIT ?``)
plus a full ``COUNT(*)`` of the same filter on every page. The indexes on
``audit_log`` are single-column, so the planner either scanned the
organization and sorted it in memory, or walked the whole timeline past
every other organization's rows. The table is append-only by a database
trigger and has neither retention nor partitioning — whatever the plan
costs today, an established instance pays it on a bigger table next
year.

Built CONCURRENTLY inside an autocommit block, following the movement
ledger's index migration: the journal is written on every meaningful
action, and the non-concurrent form would hold a write lock on it for
the length of the build.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'auditidx01'
down_revision: str | None = 'priceprec01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = 'ix_audit_log_org_created_at'


def _drop_if_invalid(conn) -> None:
    """Remove a leftover INVALID index from an interrupted concurrent build.

    CREATE INDEX CONCURRENTLY is not transactional: interrupted, it leaves an
    index that exists but cannot be used, and ``IF NOT EXISTS`` would then
    keep it that way forever. Dropping it first is what makes a re-run of
    this migration actually repair the schema.
    """
    invalid = conn.exec_driver_sql(
        'SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid '
        'WHERE c.relname = %s AND i.indisvalid = false',
        (_INDEX,),
    ).fetchone()
    if invalid:
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')


def upgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        _drop_if_invalid(conn)
        # DESC is written down rather than left to a backward scan, matching
        # the order the journal page asks for exactly.
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} '
            'ON audit_log (organization_id, created_at DESC)'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.get_bind().exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')
