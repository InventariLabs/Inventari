"""a product's unit weight and volume are exact numbers.

Revision ID: weightexact01
Revises: focfocus01
Create Date: 2026-09-02

``weight_value`` and ``volume_value`` say what one piece of a product
amounts to — "1 piece = 500 g" — and the weight total of a list multiplies
them by the quantity in SQL. The unit factors became ``numeric`` for the
sake of that arithmetic, but these two stayed ``double precision``, and
``numeric × double`` is ``double``: the "pieces" branch of the total was
still computed in floating point, one column short of exact.

numeric(14,6) holds a unit weight from a milligram to a hundred tonnes in
whatever unit it was stated in. Existing values are short decimals typed by
people, so the cast goes through text and recovers each one as written.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'weightexact01'
down_revision: str | None = 'focfocus01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ('weight_value', 'volume_value')


def upgrade() -> None:
    for column in COLUMNS:
        op.alter_column(
            'product_templates',
            column,
            existing_type=sa.Float(),
            type_=sa.Numeric(14, 6),
            existing_nullable=True,
            postgresql_using=f'{column}::text::numeric(14,6)',
        )


def downgrade() -> None:
    for column in COLUMNS:
        op.alter_column(
            'product_templates',
            column,
            existing_type=sa.Numeric(14, 6),
            type_=sa.Float(),
            existing_nullable=True,
        )
