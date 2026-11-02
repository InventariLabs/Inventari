"""add stock valuation layers and current valuation rate

Revision ID: add_svl_and_valuation_rate
Revises: cf30d6efa74e
Create Date: 2026-04-18 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'add_svl_and_valuation_rate'
down_revision: Union[str, None] = 'cf30d6efa74e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'product_templates',
        sa.Column('current_valuation_rate', sa.Numeric(precision=12, scale=2), nullable=True)
    )
    
    op.create_table(
        'stock_valuation_layers',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('organization_id', UUID(), nullable=False),
        sa.Column('product_template_id', UUID(), nullable=False),
        sa.Column('document_line_id', UUID(), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('remaining_qty', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('unit_cost', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_value', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_template_id'], ['product_templates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_line_id'], ['document_lines.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_svl_template_remaining', 'stock_valuation_layers', ['product_template_id', 'remaining_qty'])
    op.create_index('ix_svl_org_template', 'stock_valuation_layers', ['organization_id', 'product_template_id'])


def downgrade() -> None:
    op.drop_index('ix_svl_org_template', table_name='stock_valuation_layers')
    op.drop_index('ix_svl_template_remaining', table_name='stock_valuation_layers')
    op.drop_table('stock_valuation_layers')
    op.drop_column('product_templates', 'current_valuation_rate')
