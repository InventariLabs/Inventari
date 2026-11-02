"""The snapshot's column carries the width of the column it copies.

``stock_take_items.system_quantity`` stores a copy of ``items.quantity``,
which is ``numeric(12, 3)`` — up to 999,999,999.999. The copy was
``numeric(10, 3)`` and held a third of those digits, so one item over
9,999,999.999 made the INSERT overflow and the door that opens a count
answered 500 instead of a stock take. Widening a numeric never loses a
value the narrower one already held, so no backfill is needed.

``counted_quantity`` stays as it is: a number a person types, with its own
ceiling refused by name (see the counting schemas).

Revision ID: 006_system_quantity_width
Revises: 005_status_vocabulary
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '006_system_quantity_width'
down_revision: str | None = '005_status_vocabulary'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'stock_take_items',
        'system_quantity',
        type_=sa.Numeric(12, 3),
        existing_type=sa.Numeric(10, 3),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing back only succeeds for rows the smaller column still holds;
    # anything larger fails the cast rather than being silently truncated.
    op.alter_column(
        'stock_take_items',
        'system_quantity',
        type_=sa.Numeric(10, 3),
        postgresql_using='system_quantity::numeric(10, 3)',
        existing_type=sa.Numeric(12, 3),
        existing_nullable=True,
    )
