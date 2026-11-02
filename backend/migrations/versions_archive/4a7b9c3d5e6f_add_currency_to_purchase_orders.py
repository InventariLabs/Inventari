"""add currency to purchase_orders

Revision ID: 4a7b9c3d5e6f
Revises: 0dafe4a047c5
Create Date: 2026-04-25 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4a7b9c3d5e6f'
down_revision: Union[str, None] = '0dafe4a047c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'purchase_orders',
        sa.Column('currency', sa.String(3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('purchase_orders', 'currency')
