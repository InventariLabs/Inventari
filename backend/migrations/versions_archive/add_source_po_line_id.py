"""add source_po_line_id to document_lines

Revision ID: add_source_po_line_id
Revises: add_purchase_orders
Create Date: 2026-04-18 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'add_source_po_line_id'
down_revision: Union[str, None] = 'add_purchase_orders'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column('source_po_line_id', UUID(), nullable=True),
    )
    op.create_index(
        'ix_document_lines_source_po_line_id',
        'document_lines',
        ['source_po_line_id'],
    )
    op.create_foreign_key(
        'fk_document_lines_source_po_line_id',
        'document_lines',
        'purchase_order_lines',
        ['source_po_line_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_document_lines_source_po_line_id', 'document_lines', type_='foreignkey')
    op.drop_index('ix_document_lines_source_po_line_id', table_name='document_lines')
    op.drop_column('document_lines', 'source_po_line_id')
