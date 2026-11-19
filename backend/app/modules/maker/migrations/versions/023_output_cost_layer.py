"""maker module — a run keeps the cost layer its output opened.

Undoing a completed run takes the output off the books at what the run put
in, and the layer is the only place that value is recorded: the oldest open
layer of the product may belong to an earlier run at a different cost.
``maker_production_orders.output_layer_id`` names it, so the reversal drains
the run's own layer. NULL on a run filled in portions (each portion keeps its
own) and on runs that closed before the column existed.

Revision ID: 023_output_cost_layer
Revises: 021_label_facts
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '023_output_cost_layer'
down_revision: str | None = '021_label_facts'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_orders',
        sa.Column(
            'output_layer_id',
            sa.Uuid(),
            sa.ForeignKey('stock_valuation_layers.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('maker_production_orders', 'output_layer_id')
