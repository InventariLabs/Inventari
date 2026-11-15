"""maker module — a production run names the batch its output goes into.

``maker_production_orders.output_lot_name`` (VARCHAR(100), nullable): the
batch the run's output is put on the shelf in, opened on completion. NULL —
every run stored so far — keeps the output unbatched, as before.

Revision ID: 016_add_output_lot_name
Revises: 015_default_result_margin
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '016_add_output_lot_name'
down_revision: str | None = '015_default_result_margin'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_orders',
        sa.Column('output_lot_name', sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('maker_production_orders', 'output_lot_name')
