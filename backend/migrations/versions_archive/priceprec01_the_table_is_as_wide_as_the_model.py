"""a numeric column is as wide in the table as the model declares.

Revision ID: priceprec01
Revises: weightexact01
Create Date: 2026-09-02

The baseline created several exact columns as bare ``numeric`` while the
models declare a width: a price of ``Numeric(10, 2)``, quantities of
``Numeric(12, 3)``, a layer value of ``Numeric(14, 2)``. A table wider than
its model accepts what the model promises not to hold — a third decimal on
a price — and the test databases, built from the model, cannot reproduce
it. ``items.quantity`` was aligned by hand once; a gate now compares every
numeric column against the model, and these are the ones it found.

Each cast rounds to the declared scale, which is what the code already did
before writing: the receipt rounds a unit cost and a total, and a quantity
is validated to its unit's step. A value wider than the declared precision
would fail the cast and name the column, which is the right outcome — it
would be a row the model could not have written.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'priceprec01'
down_revision: str | None = 'weightexact01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, precision, scale, nullable)
COLUMNS = (
    ('items', 'purchase_price', 10, 2, True),
    ('stock_quants', 'quantity', 12, 3, False),
    ('stock_quants', 'reserved_quantity', 12, 3, False),
    ('stock_valuation_layers', 'quantity', 12, 3, False),
    ('stock_valuation_layers', 'remaining_qty', 12, 3, False),
    ('stock_valuation_layers', 'total_value', 14, 2, False),
)


def upgrade() -> None:
    for table, column, precision, scale, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(),
            type_=sa.Numeric(precision, scale),
            existing_nullable=nullable,
            postgresql_using=f'round({column}, {scale})',
        )


def downgrade() -> None:
    for table, column, precision, scale, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(precision, scale),
            type_=sa.Numeric(),
            existing_nullable=nullable,
        )
