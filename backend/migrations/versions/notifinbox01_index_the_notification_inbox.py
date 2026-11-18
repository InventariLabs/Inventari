"""index the notification inbox - what the bell reads

The bell asks for one user's notifications, often only the unread ones, newest
first, and all the index on ``user_id`` could do was hand over every
notification that user ever had. The new index answers the unread question in
its own order. It starts with ``user_id``, so it also serves everything the old
index did, the cascade from a deleted user included, and the old one goes.

Revision ID: notifinbox01
Revises: layerinternal01
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'notifinbox01'
down_revision: str | None = 'layerinternal01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEX = 'ix_notifications_user_read_created'
_REPLACED_INDEX = 'ix_notifications_user_id'


def _build(conn, name: str, columns: str) -> None:
    """Build an index, first removing what an interrupted build left INVALID."""
    invalid = conn.exec_driver_sql(
        'SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid '
        'WHERE c.relname = %s AND i.indisvalid = false',
        (name,),
    ).fetchone()
    if invalid:
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {name}')
    conn.exec_driver_sql(
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON notifications ({columns})'
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        _build(conn, _INDEX, 'user_id, is_read, created_at')
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_REPLACED_INDEX}')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        _build(conn, _REPLACED_INDEX, 'user_id')
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')
