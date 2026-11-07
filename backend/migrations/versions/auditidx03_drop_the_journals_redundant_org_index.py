"""drop the journal's single-column organization index

``ix_audit_log_organization_id`` is the leading column of both composite
indexes the journal is read through (``ix_audit_log_org_created_at_id`` and
``ix_audit_log_org_type_created_at``), so everything it answers they answer
too. Measured on a running stack with 600,000 entries over ten organizations,
the count of one organization reads the same 8,518 buffers of heap with or
without it; without it the planner reads the composite instead, about 400
buffers more of index (4%). The journal is written on every meaningful
action and each write pays for every index it carries.

The other index the journal was suspected of carrying needlessly, on
``created_at`` alone, is already gone: the baseline does not create it.

Dropped CONCURRENTLY inside an autocommit block, so the drop does not wait
behind the journal's writers while it holds a lock on the table. The
downgrade rebuilds it the same way, with the guard against the INVALID
leftover an interrupted concurrent build leaves behind.

Revision ID: auditidx03
Revises: archivedat01
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'auditidx03'
down_revision: str | None = 'archivedat01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = 'ix_audit_log_organization_id'


def _drop_if_invalid(conn) -> None:
    """Remove a leftover INVALID index from an interrupted concurrent build."""
    invalid = conn.exec_driver_sql(
        'SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid '
        'WHERE c.relname = %s AND i.indisvalid = false',
        (_INDEX,),
    ).fetchone()
    if invalid:
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.get_bind().exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        _drop_if_invalid(conn)
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} '
            'ON audit_log (organization_id)'
        )
