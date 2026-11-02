"""maker module — add financial result snapshot columns to production orders.

Additive columns on ``maker_production_orders``:

- ``unit_cost_snapshot`` NUMERIC(12,4) — unit cost at completion (total / actual)
- ``reference_price_snapshot`` NUMERIC(12,2) — recipe reference price at completion
- ``result_per_unit`` NUMERIC(12,2) — reference_price − unit_cost (per unit of output)
- ``result_per_batch`` NUMERIC(12,2) — result_per_unit × recipe.batch_yield_qty

The snapshot is self-contained: it survives recipe edits and deletions and
powers the catalog result, the production list "result" column, the monthly
dashboard widget and the recipe cost history. Legacy orders (pre-0a,
``recipe_id IS NULL``) keep NULL snapshots and display "—".

Revision ID: 008_add_result_snapshot
Revises: 007_add_availability_shortage
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '008_add_result_snapshot'
down_revision: str | None = '007_add_availability_shortage'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_orders',
        sa.Column('unit_cost_snapshot', sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('reference_price_snapshot', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('result_per_unit', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('result_per_batch', sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('maker_production_orders', 'result_per_batch')
    op.drop_column('maker_production_orders', 'result_per_unit')
    op.drop_column('maker_production_orders', 'reference_price_snapshot')
    op.drop_column('maker_production_orders', 'unit_cost_snapshot')
