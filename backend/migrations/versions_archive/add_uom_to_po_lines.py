"""add uom_id to purchase_order_lines

Revision ID: add_uom_to_po_lines
Revises: add_source_po_line_id
Create Date: 2026-04-18 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'add_uom_to_po_lines'
down_revision: Union[str, None] = 'add_source_po_line_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'purchase_order_lines',
        sa.Column('uom_id', UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_po_lines_uom_id',
        'purchase_order_lines',
        'uoms',
        ['uom_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_po_lines_uom_id', 'purchase_order_lines', type_='foreignkey')
    op.drop_column('purchase_order_lines', 'uom_id')
