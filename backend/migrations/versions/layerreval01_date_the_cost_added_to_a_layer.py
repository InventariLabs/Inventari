"""date the cost that was added to a receipt layer after it was posted

A cost that is only known after the goods came in — the corks and labour of a
production run whose bottles were put on the shelf before the run closed — is
put on what is left of the receipt's layer. The layer reads what it is worth
now, which is what the stock value and the rates need; but a report about an
instant before that would then read the cost a day it was not yet known.

``revalued_at`` is when the cost was added, and ``unit_cost_before`` and
``cost_basis_before`` what the layer read just before: the as-of valuation
takes them for an instant earlier than ``revalued_at``. All three stay NULL on
a layer nobody revalued, which is every layer already there.

Revision ID: layerreval01
Revises: ledgertotals03
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'layerreval01'
down_revision: str | None = 'ledgertotals03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_valuation_layers',
        sa.Column('revalued_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'stock_valuation_layers',
        sa.Column('unit_cost_before', sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        'stock_valuation_layers',
        sa.Column('cost_basis_before', sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('stock_valuation_layers', 'cost_basis_before')
    op.drop_column('stock_valuation_layers', 'unit_cost_before')
    op.drop_column('stock_valuation_layers', 'revalued_at')
