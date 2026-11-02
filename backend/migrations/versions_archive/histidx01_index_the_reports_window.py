"""index item history on the window the reports read

Revision ID: histidx01
Revises: evtoutbox02
Create Date: 2026-10-07

Consumption, waste and the check whether a window is valued all ask the same
question of ``item_history``: one organization, one kind of event, since a
date. The table had indexes on (item_id, created_at), the organization, the
user and the source document — none of which serves that filter, so every
report scanned the organization's whole history and threw most of it away.
Nothing archives a history row, so the table only grows.

The reports now filter on ``organization_id`` as well, so a row that never
had one would fall out of them. The application has always written it, but
the column is nullable and older rows may predate that; they take the
organization of the record they belong to before the index is built.

Built CONCURRENTLY inside an autocommit block, as ``smvmoved01`` does:
``item_history`` is written by every stock movement, and the plain form would
hold a write lock on it for the length of the build.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'histidx01'
down_revision: str | None = 'evtoutbox02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = 'ix_item_history_org_action_created'


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
    op.execute(
        'UPDATE item_history h SET organization_id = i.organization_id '
        'FROM items i WHERE h.item_id = i.id AND h.organization_id IS NULL'
    )
    with op.get_context().autocommit_block():
        # An offline script (``--sql``) has no database to ask, so it can
        # only write the build; the repair of an interrupted one is online.
        if not op.get_context().as_sql:
            _drop_if_invalid(op.get_bind())
        op.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} '
            'ON item_history (organization_id, action, created_at)'
        )


def downgrade() -> None:
    # The backfilled organizations stay: they are what the application
    # writes anyway, and nothing can tell them from the rows it wrote.
    with op.get_context().autocommit_block():
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')
