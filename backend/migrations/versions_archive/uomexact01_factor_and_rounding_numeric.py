"""a unit's conversion factor is an exact number.

Revision ID: uomexact01
Revises: ckvalid01
Create Date: 2026-09-01

``factor`` and ``rounding`` were ``double precision``. The Python paths
recovered most of the damage — ``Decimal(str(x))`` on a float gives back the
short decimal it was written as — but SQL had no such rescue: ``numeric ×
double`` is ``double``, so every expression multiplying a stored quantity by
a factor left exact arithmetic the moment it touched this table.

A conversion coefficient is a definition, not a measurement. There is no
reason for it to be the one approximate number in a chain of exact ones.

Eighteen digits with nine after the point covers what a unit table needs:
3785.41 for a US gallon in millilitres at one end, 0.001 for a milligram in
grams at the other, with room for a conversion somebody defines by hand.
``rounding`` needs far less and gets numeric(12,6).

Existing values are seeded constants written as short decimals, so the cast
through text recovers each one exactly rather than carrying a float's tail
into the new column.

Downgrade returns both columns to double precision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'uomexact01'
down_revision: str | None = 'ckvalid01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'uoms',
        'factor',
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 9),
        existing_nullable=False,
        postgresql_using='factor::text::numeric(18,9)',
    )
    op.alter_column(
        'uoms',
        'rounding',
        existing_type=sa.Float(),
        type_=sa.Numeric(12, 6),
        existing_nullable=False,
        postgresql_using='rounding::text::numeric(12,6)',
    )


def downgrade() -> None:
    op.alter_column(
        'uoms',
        'rounding',
        existing_type=sa.Numeric(12, 6),
        type_=sa.Float(),
        existing_nullable=False,
    )
    op.alter_column(
        'uoms',
        'factor',
        existing_type=sa.Numeric(18, 9),
        type_=sa.Float(),
        existing_nullable=False,
    )
