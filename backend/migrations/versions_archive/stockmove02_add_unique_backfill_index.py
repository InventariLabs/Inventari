"""add partial unique index for backfilled StockMove rows

Revision ID: stockmove02
Revises: stockmove01
Create Date: 2026-06-23

The backfill CLI translates ItemHistory → StockMove with
``reference_type='item_history'`` and ``reference_id=ItemHistory.id``.

This partial UNIQUE index makes the backfill idempotent: a re-run
cannot insert the same ItemHistory twice.  It only applies to the
backfill namespace — moves from ``reference_type='item'`` (written by
``_sync_stock_quant``) can have many rows per item.id, so they must
not share the constraint.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'stockmove02'
down_revision: str | None = 'stockmove01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'uq_stock_moves_backfill_ref',
        'stock_moves',
        ['reference_type', 'reference_id'],
        unique=True,
        postgresql_where="reference_type = 'item_history'",
    )


def downgrade() -> None:
    op.drop_index('uq_stock_moves_backfill_ref', table_name='stock_moves')
