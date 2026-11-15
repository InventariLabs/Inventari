"""maker module — a run can be started and finished apart; a line can be made fresh.

``maker_bom_lines.make_fresh`` marks an ingredient that is always made through
its own recipe and never taken from its stock. Every existing line gets
``false``, which takes stock first.

``maker_production_orders`` gains ``started_on``, ``started_at``, ``material_cost`` and
``steps`` for a run that is started, filled in portions and finished later;
``maker_production_portions`` holds those portions. All of it is NULL / empty
on runs completed in one step.

Revision ID: 020_staged_runs_and_stock_first
Revises: 019_output_batch_and_papers
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '020_staged_runs_and_stock_first'
down_revision: str | None = '019_output_batch_and_papers'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_bom_lines',
        sa.Column(
            'make_fresh', sa.Boolean(), nullable=False, server_default='false'
        ),
    )
    op.add_column(
        'maker_production_orders', sa.Column('started_on', sa.Date(), nullable=True)
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('material_cost', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('unshelved_cost', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('steps', postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        'maker_production_portions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.Uuid(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'production_order_id',
            sa.Uuid(),
            sa.ForeignKey('maker_production_orders.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('qty', sa.Numeric(12, 3), nullable=False),
        sa.Column('made_on', sa.Date(), nullable=False),
        sa.Column('lot_name', sa.String(100), nullable=True),
        sa.Column(
            'item_id',
            sa.Uuid(),
            sa.ForeignKey('items.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('unit_cost', sa.Numeric(12, 4), nullable=True),
        sa.Column(
            'layer_id',
            sa.Uuid(),
            sa.ForeignKey('stock_valuation_layers.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_prod_portion_order', 'maker_production_portions', ['production_order_id']
    )


def downgrade() -> None:
    op.drop_index('ix_prod_portion_order', table_name='maker_production_portions')
    op.drop_table('maker_production_portions')
    op.drop_column('maker_production_orders', 'steps')
    op.drop_column('maker_production_orders', 'unshelved_cost')
    op.drop_column('maker_production_orders', 'material_cost')
    op.drop_column('maker_production_orders', 'started_at')
    op.drop_column('maker_production_orders', 'started_on')
    op.drop_column('maker_bom_lines', 'make_fresh')
