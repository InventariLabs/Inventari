"""index the movement ledger on the date a movement is about

Revision ID: smvmoved01
Revises: uompcs01
Create Date: 2026-08-30

The ledger list sorts by ``coalesce(completed_at, created_at) DESC, id`` —
``completed_at`` is the date the movement belongs to, ``created_at`` only
stands in for rows that never carried one. That expression is neither column
on its own, so the existing single-column indexes on both cannot serve the
sort: Postgres reads the organization's entire ledger and sorts it in memory
to return a page of fifty. Measured on ten thousand movements the plan was
``Seq Scan`` + ``top-N heapsort``, which costs 3 ms and hides the problem;
nothing archives a movement, so the table only grows.

Built CONCURRENTLY inside an autocommit block, following the trigram index
migration: ``stock_moves`` is the largest table in an established instance
and the non-concurrent form would hold a write lock on it for the length of
the build — meaning nobody could receive or pick anything meanwhile.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'smvmoved01'
down_revision: str | None = 'uompcs01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = 'ix_stock_moves_org_moved_at'


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
        # DESC is written down rather than left to a backward scan: reading
        # an ascending index backwards would order the trailing id the wrong
        # way, and the id is the tiebreak the pagination depends on.
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} '
            'ON stock_moves '
            '(organization_id, coalesce(completed_at, created_at) DESC, id)'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.get_bind().exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')
