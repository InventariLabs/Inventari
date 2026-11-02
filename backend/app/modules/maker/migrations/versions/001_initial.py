"""maker module — create BOM, production order, and line tables.

Initial migration for the maker module (BOM, production orders, audit lines).
Tables (creation order respects FK dependencies):
- maker_bom_lines (FK → organizations, product_templates x2)
- maker_production_orders (FK → organizations, product_templates, storage_locations)
- maker_production_order_lines (FK → maker_production_orders, product_templates, storage_locations)

Revision ID: 001_initial
Revises: None
Create Date: 2026-07-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('maker',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- maker_bom_lines ---
    create_table_if_absent(
        'maker_bom_lines',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'parent_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'child_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('qty_per_unit', sa.Numeric(12, 4), nullable=False),
        sa.Column('unit', sa.String(8), nullable=False),
        sa.Column(
            'yield_loss_pct',
            sa.Numeric(5, 2),
            nullable=False,
            server_default='0',
        ),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.UniqueConstraint(
            'parent_template_id',
            'child_template_id',
            name='uq_bom_parent_child',
        ),
        sa.CheckConstraint('qty_per_unit > 0', name='ck_bom_qty_positive'),
        sa.CheckConstraint(
            'parent_template_id <> child_template_id',
            name='ck_bom_no_self',
        ),
        sa.CheckConstraint(
            'yield_loss_pct >= 0 AND yield_loss_pct <= 100',
            name='ck_bom_yield_range',
        ),
    )
    create_index_if_absent('ix_bom_parent', 'maker_bom_lines', ['parent_template_id'])
    create_index_if_absent('ix_bom_org', 'maker_bom_lines', ['organization_id'])

    # --- maker_production_orders ---
    create_table_if_absent(
        'maker_production_orders',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'output_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id'),
            nullable=False,
        ),
        sa.Column('planned_qty', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'output_storage_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id'),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.String(16),
            nullable=False,
            server_default='DRAFT',
        ),
        sa.Column('total_cost', sa.Numeric(12, 2), nullable=True),
        sa.Column('production_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=True,
        ),
        sa.Column(
            'completed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    create_index_if_absent(
        'ix_prod_org_status',
        'maker_production_orders',
        ['organization_id', 'status'],
    )
    create_index_if_absent(
        'ix_prod_org_output',
        'maker_production_orders',
        ['organization_id', 'output_template_id'],
    )

    # --- maker_production_order_lines ---
    create_table_if_absent(
        'maker_production_order_lines',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'production_order_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('maker_production_orders.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'child_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id'),
            nullable=False,
        ),
        sa.Column('consumed_qty', sa.Numeric(12, 4), nullable=False),
        sa.Column('unit', sa.String(8), nullable=False),
        sa.Column(
            'source_storage_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id'),
            nullable=True,
        ),
        sa.Column('unit_cost_snapshot', sa.Numeric(12, 4), nullable=True),
        sa.Column('cost_source', sa.String(16), nullable=True),
    )
    create_index_if_absent(
        'ix_prod_line_order',
        'maker_production_order_lines',
        ['production_order_id'],
    )


def downgrade() -> None:
    # Drop children first (FK chain: lines → orders)
    op.drop_index(
        'ix_prod_line_order',
        table_name='maker_production_order_lines',
    )
    op.drop_table('maker_production_order_lines')

    op.drop_index(
        'ix_prod_org_output',
        table_name='maker_production_orders',
    )
    op.drop_index(
        'ix_prod_org_status',
        table_name='maker_production_orders',
    )
    op.drop_table('maker_production_orders')

    op.drop_index('ix_bom_org', table_name='maker_bom_lines')
    op.drop_index('ix_bom_parent', table_name='maker_bom_lines')
    op.drop_table('maker_bom_lines')
