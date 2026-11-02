"""add check constraints on stock_quants and items

Revision ID: e3ffe1ea0d75
Revises: 30cec1e60faf
Create Date: 2026-06-14 16:26:50.815596

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3ffe1ea0d75'
down_revision: Union[str, None] = '30cec1e60faf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(table: str, name: str) -> bool:
    """Whether the database already carries this constraint.

    A database that ran the historical migration chain (before the baseline
    snapshot) already holds `ck_stock_quants_reserved_le_quantity` under this
    same name; a fresh one is built from the snapshot and needs it added.
    """
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                'SELECT 1 FROM pg_constraint '
                'WHERE conname = :name AND conrelid = to_regclass(:table)'
            ),
            {'name': name, 'table': f'public.{table}'},
        ).scalar()
    )


def upgrade() -> None:
    # Use NOT VALID so existing rows are not scanned — only new/updated
    # rows are enforced. This avoids long locks on large tables.
    # Run VALIDATE CONSTRAINT separately to check existing rows async.
    if not _constraint_exists('stock_quants', 'ck_stock_quants_quantity_nonneg'):
        op.execute(
            sa.text(
                'ALTER TABLE stock_quants '
                "ADD CONSTRAINT ck_stock_quants_quantity_nonneg "
                'CHECK (quantity >= 0) NOT VALID'
            )
        )
    if not _constraint_exists('stock_quants', 'ck_stock_quants_reserved_nonneg'):
        op.execute(
            sa.text(
                'ALTER TABLE stock_quants '
                "ADD CONSTRAINT ck_stock_quants_reserved_nonneg "
                'CHECK (reserved_quantity >= 0) NOT VALID'
            )
        )
    if not _constraint_exists(
        'stock_quants', 'ck_stock_quants_reserved_le_quantity'
    ):
        op.execute(
            sa.text(
                'ALTER TABLE stock_quants '
                "ADD CONSTRAINT ck_stock_quants_reserved_le_quantity "
                'CHECK (reserved_quantity <= quantity) NOT VALID'
            )
        )
    if not _constraint_exists('items', 'ck_items_quantity_nonneg'):
        op.execute(
            sa.text(
                'ALTER TABLE items '
                "ADD CONSTRAINT ck_items_quantity_nonneg "
                'CHECK (quantity >= 0) NOT VALID'
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text('ALTER TABLE items DROP CONSTRAINT IF EXISTS ck_items_quantity_nonneg')
    )
    op.execute(
        sa.text(
            'ALTER TABLE stock_quants DROP CONSTRAINT IF EXISTS ck_stock_quants_reserved_le_quantity'
        )
    )
    op.execute(
        sa.text(
            'ALTER TABLE stock_quants DROP CONSTRAINT IF EXISTS ck_stock_quants_reserved_nonneg'
        )
    )
    op.execute(
        sa.text(
            'ALTER TABLE stock_quants DROP CONSTRAINT IF EXISTS ck_stock_quants_quantity_nonneg'
        )
    )