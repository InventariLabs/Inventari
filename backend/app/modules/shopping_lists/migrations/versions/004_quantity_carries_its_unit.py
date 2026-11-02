"""shopping_lists: quantity carries the unit's step, not whole pieces.

The list stored quantities as integers, so a recipe asking for half a
kilo of flour could only land as "1 kg" — the storage itself forced the
lie the rounding now refuses to tell. Measured units (grams, litres,
centimetres) keep their fractions; countable units are unaffected, whole
numbers read back exactly as before.

Revision ID: 004_quantity_carries_its_unit
Revises: 003_item_note_data
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '004_quantity_carries_its_unit'
down_revision: str | None = '003_item_note_data'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ('shopping_list_items', 'shopping_list_history')


def upgrade() -> None:
    for table in TABLES:
        op.alter_column(
            table,
            'quantity',
            type_=sa.Numeric(12, 3),
            postgresql_using='quantity::numeric(12, 3)',
            existing_type=sa.Integer(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Rounding measured quantities back to whole pieces loses the fraction
    # — the direction this revision exists to stop — so the downgrade
    # truncates deliberately and loudly via ::int.
    for table in TABLES:
        op.alter_column(
            table,
            'quantity',
            type_=sa.Integer(),
            postgresql_using='quantity::int',
            existing_type=sa.Numeric(12, 3),
            existing_nullable=False,
        )
