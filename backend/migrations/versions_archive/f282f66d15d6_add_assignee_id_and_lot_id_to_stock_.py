"""add assignee_id and lot_id to stock_take_items

Revision ID: f282f66d15d6
Revises: 16707466e6f8
Create Date: 2026-04-27 14:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f282f66d15d6'
down_revision: Union[str, None] = '16707466e6f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_take_items', sa.Column(
        'assignee_id', sa.UUID(), nullable=True
    ))
    op.add_column('stock_take_items', sa.Column(
        'lot_id', sa.UUID(), nullable=True
    ))
    op.create_foreign_key(
        'fk_stock_take_items_assignee', 'stock_take_items',
        'users', ['assignee_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_stock_take_items_lot', 'stock_take_items',
        'stock_lots', ['lot_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_stock_take_items_lot', 'stock_take_items', type_='foreignkey')
    op.drop_constraint('fk_stock_take_items_assignee', 'stock_take_items', type_='foreignkey')
    op.drop_column('stock_take_items', 'lot_id')
    op.drop_column('stock_take_items', 'assignee_id')
