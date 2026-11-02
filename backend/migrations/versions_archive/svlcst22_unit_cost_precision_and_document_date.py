"""valuation layers: unit_cost to 4 dp, carry the receipt's business date

``unit_cost`` was Numeric(12,2): per gram or per millilitre a cost of
0.004 rounded to 0.00 — ERP systems keep 4–6 decimal places for exactly
this. The layer also gains ``document_date``, the receipt's business
date, so FIFO consumes in business-date order rather than in the order
rows happened to be written; rows written before the column exist carry
NULL and fall back to their write time.

Revision ID: svlcst22
Revises: a1c49683733c
Create Date: 2026-08-30 21:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'svlcst22'
down_revision: Union[str, None] = 'a1c49683733c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'stock_valuation_layers',
        'unit_cost',
        existing_type=sa.Numeric(12, 2),
        type_=sa.Numeric(12, 4),
        existing_nullable=False,
    )
    op.add_column(
        'stock_valuation_layers',
        sa.Column('document_date', sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('stock_valuation_layers', 'document_date')
    # Layers whose 4th and 3rd decimal are non-zero lose them here; a cost
    # stated per gram does not survive a return to two decimal places, and
    # that loss is why the column was widened.
    op.alter_column(
        'stock_valuation_layers',
        'unit_cost',
        existing_type=sa.Numeric(12, 4),
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        postgresql_using='unit_cost::numeric(12, 2)',
    )
