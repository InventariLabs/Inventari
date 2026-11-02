"""maker module — a run recorded after the fact names what the records lacked.

``maker_production_order_lines.shortfall_qty`` (NUMERIC(12, 4), nullable): the
part of the line's consumption the stock records did not hold when a run that
had already happened was recorded. The run is not refused for it — the goods
were used — and the ingredient is put up for a count instead.

Revision ID: 014_add_line_shortfall
Revises: 013_sort_order_not_null
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '014_add_line_shortfall'
down_revision: str | None = '013_sort_order_not_null'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_order_lines',
        sa.Column('shortfall_qty', sa.Numeric(12, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('maker_production_order_lines', 'shortfall_qty')
