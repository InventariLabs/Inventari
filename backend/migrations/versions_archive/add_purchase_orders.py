"""create purchase orders tables

Revision ID: add_purchase_orders
Revises: add_svl_and_valuation_rate
Create Date: 2026-04-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'add_purchase_orders'
down_revision: Union[str, None] = 'add_svl_and_valuation_rate'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'purchase_orders',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('organization_id', UUID(), nullable=False),
        sa.Column('number', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='DRAFT'),
        sa.Column('partner_id', UUID(), nullable=True),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', UUID(), nullable=False),
        sa.Column('confirmed_by', UUID(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by', UUID(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['confirmed_by'], ['users.id']),
        sa.ForeignKeyConstraint(['cancelled_by'], ['users.id']),
        sa.UniqueConstraint('number'),
    )
    op.create_index('ix_purchase_orders_org_id', 'purchase_orders', ['organization_id'])
    op.create_index('ix_purchase_orders_status', 'purchase_orders', ['status'])

    op.create_table(
        'purchase_order_lines',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('purchase_order_id', UUID(), nullable=False),
        sa.Column('product_template_id', UUID(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('quantity_ordered', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('quantity_received', sa.Numeric(precision=12, scale=3), nullable=False, server_default='0'),
        sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('line_number', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['purchase_order_id'], ['purchase_orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_template_id'], ['product_templates.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_po_lines_order_id', 'purchase_order_lines', ['purchase_order_id'])


def downgrade() -> None:
    op.drop_index('ix_po_lines_order_id', table_name='purchase_order_lines')
    op.drop_table('purchase_order_lines')
    op.drop_index('ix_purchase_orders_status', table_name='purchase_orders')
    op.drop_index('ix_purchase_orders_org_id', table_name='purchase_orders')
    op.drop_table('purchase_orders')
