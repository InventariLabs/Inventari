"""add tax_rate to purchase_order_lines

Revision ID: add_tax_rate_to_po_lines
Revises: add_uom_to_po_lines
Create Date: 2026-04-19 00:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'add_tax_rate_to_po_lines'
down_revision: Union[str, None] = 'add_uom_to_po_lines'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'purchase_order_lines',
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('purchase_order_lines', 'tax_rate')
