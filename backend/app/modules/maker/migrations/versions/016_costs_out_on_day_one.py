"""maker module — a formula costs out on day one, and a run shows both costs.

Three inputs a craft producer prices a batch from that the module did not
hold:

* ``maker_ingredient_prices`` — a price typed once on a product with no cost
  layer and no supplier quote, the last answer the shared estimate asks.
* ``maker_module_settings.labor_hourly_rate`` — what an hour of the
  organization's own work costs, so a formula's labour is its steps' minutes
  at that rate rather than a lump sum typed per batch.
* ``maker_production_orders.estimated_total_cost`` and the two estimate
  snapshots on ``maker_production_order_lines`` — what the formula predicted
  when the run closed, kept beside what it actually cost so the page can say
  whether a difference came from price or from quantity.

Revision ID: 016_costs_out_on_day_one
Revises: 015_default_result_margin
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '016_costs_out_on_day_one'
down_revision: str | None = '015_default_result_margin'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_module_settings',
        sa.Column(
            'labor_hourly_rate',
            sa.Numeric(12, 2),
            nullable=False,
            server_default='0',
        ),
    )
    op.create_table(
        'maker_ingredient_prices',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('product_template_id', sa.Uuid(), nullable=False),
        sa.Column('unit_price', sa.Numeric(12, 4), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['product_template_id'], ['product_templates.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_maker_price_org_template',
        ),
    )
    op.create_index(
        'ix_maker_price_org', 'maker_ingredient_prices', ['organization_id']
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('estimated_total_cost', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'maker_production_order_lines',
        sa.Column('estimated_qty', sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        'maker_production_order_lines',
        sa.Column('estimated_unit_cost_snapshot', sa.Numeric(12, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('maker_production_order_lines', 'estimated_unit_cost_snapshot')
    op.drop_column('maker_production_order_lines', 'estimated_qty')
    op.drop_column('maker_production_orders', 'estimated_total_cost')
    op.drop_index('ix_maker_price_org', table_name='maker_ingredient_prices')
    op.drop_table('maker_ingredient_prices')
    op.drop_column('maker_module_settings', 'labor_hourly_rate')
