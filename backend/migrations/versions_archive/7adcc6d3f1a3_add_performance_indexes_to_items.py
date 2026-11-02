"""add_performance_indexes_to_items

Revision ID: 7adcc6d3f1a3
Revises: 4af6cb8153d5
Create Date: 2026-02-15 10:46:36.994861

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7adcc6d3f1a3'
down_revision: Union[str, None] = '4af6cb8153d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adding indexes for commonly queried and sorted columns with safety checks
    try:
        op.create_index('ix_items_expiry_date', 'items', ['expiry_date'], unique=False)
    except Exception:
        pass
    try:
        op.create_index('ix_items_created_at', 'items', ['created_at'], unique=False)
    except Exception:
        pass
    try:
        op.create_index('ix_items_quantity', 'items', ['quantity'], unique=False)
    except Exception:
        pass


def downgrade() -> None:
    op.drop_index('ix_items_expiry_date', table_name='items')
    op.drop_index('ix_items_created_at', table_name='items')
    op.drop_index('ix_items_quantity', table_name='items')
