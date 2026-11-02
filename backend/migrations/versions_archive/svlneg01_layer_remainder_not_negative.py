"""a valuation layer cannot hold less than nothing.

Revision ID: svlneg01
Revises: storagelevel03
Create Date: 2026-09-01

A layer holds what is left of one receipt, and ``remaining_qty`` is only ever
decremented by the smaller of "what is left" and "what is leaving" — so below
zero is not a state the arithmetic can reach. It could be reached anyway:
draining read the remainder and wrote it back without holding the row, and
the quant paths do not protect this because they lock per location while a
layer belongs to a product. Two outflows of the same goods from two different
shelves each found the layer sufficient and one of the two writes survived.

The drain takes a row lock now. This constraint is the table's own answer, so
damage of that shape stops looking like data.

Any row already below zero is brought up to zero first: it is the state the
code has believed all along, and a constraint that cannot be added is a
constraint nobody has.

Downgrade drops the constraint.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'svlneg01'
down_revision: str | None = 'storagelevel03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        'UPDATE stock_valuation_layers SET remaining_qty = 0 WHERE remaining_qty < 0'
    )
    op.create_check_constraint(
        'ck_svl_remaining_not_negative',
        'stock_valuation_layers',
        'remaining_qty >= 0',
    )


def downgrade() -> None:
    op.drop_constraint(
        'ck_svl_remaining_not_negative',
        'stock_valuation_layers',
        type_='check',
    )
