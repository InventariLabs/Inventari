"""add missing schema columns to shopping_lists, stock_takes

Revision ID: d1e2f3a4b5c6
Revises: c0a1b2c3d4e5
Create Date: 2026-06-20 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT to_regclass(:t)"), {'t': f'public.{table_name}'}
        ).scalar()
    )


def upgrade() -> None:
    if not _table_exists('shopping_lists') or not _table_exists('stock_takes'):
        return

    # shopping_lists: add status, completed_at, archived_at
    op.add_column(
        'shopping_lists',
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
    )
    op.add_column(
        'shopping_lists',
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'shopping_lists',
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_shopping_lists_status', 'shopping_lists', ['status'])

    # stock_takes: add deleted_at
    op.add_column(
        'stock_takes',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if not _table_exists('shopping_lists') or not _table_exists('stock_takes'):
        return

    op.drop_column('stock_takes', 'deleted_at')
    op.drop_index('ix_shopping_lists_status', table_name='shopping_lists')
    op.drop_column('shopping_lists', 'archived_at')
    op.drop_column('shopping_lists', 'completed_at')
    op.drop_column('shopping_lists', 'status')
