"""purchase_orders module baseline — create purchase_orders tables.

Initial migration for the purchase_orders module, extracted from core baseline_001
as part of the module migration isolation effort.

These tables were previously created by the consolidated
``baseline_001_full_schema.py``. They now belong to the purchase_orders module.

This migration reflects the FINAL state after core migration ``poorguniq01``
(non-unique index on ``number`` + unique constraint on ``(org, number)``).

Tables:
- purchase_orders (with uq_purchase_orders_org_number unique constraint)
- purchase_order_lines

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('purchase_orders',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'purchase_orders',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('number', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column(
            'partner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
        ),
        sa.Column('scheduled_date', sa.Date()),
        sa.Column('notes', sa.Text()),
        sa.Column('currency', sa.String(3)),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column(
            'confirmed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
        ),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.Column(
            'cancelled_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
        ),
        sa.Column('cancelled_at', sa.DateTime(timezone=True)),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'number',
            name='uq_purchase_orders_org_number',
        ),
    )
    create_index_if_absent('ix_purchase_orders_number', 'purchase_orders', ['number'])
    create_index_if_absent('ix_purchase_orders_status', 'purchase_orders', ['status'])
    create_index_if_absent(
        'ix_purchase_orders_organization_id',
        'purchase_orders',
        ['organization_id'],
    )

    create_table_if_absent(
        'purchase_order_lines',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'purchase_order_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('purchase_orders.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='SET NULL'),
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('quantity_ordered', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'quantity_received',
            sa.Numeric(12, 3),
            nullable=False,
            server_default='0',
        ),
        sa.Column('unit_price', sa.Numeric(12, 2)),
        sa.Column(
            'uom_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id'),
        ),
        sa.Column('tax_rate', sa.Numeric(5, 2)),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text()),
    )
    create_index_if_absent(
        'ix_purchase_order_lines_purchase_order_id',
        'purchase_order_lines',
        ['purchase_order_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_purchase_order_lines_purchase_order_id',
        table_name='purchase_order_lines',
    )
    op.drop_table('purchase_order_lines')

    op.drop_index('ix_purchase_orders_organization_id', table_name='purchase_orders')
    op.drop_index('ix_purchase_orders_status', table_name='purchase_orders')
    op.drop_index('ix_purchase_orders_number', table_name='purchase_orders')
    op.drop_table('purchase_orders')
