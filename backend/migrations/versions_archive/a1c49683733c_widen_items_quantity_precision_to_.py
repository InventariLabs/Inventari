"""widen items quantity precision to numeric 12 3

Item.quantity carried Numeric(10,3) while StockQuant.quantity carries
Numeric(12,3): the cache and its source of truth disagreed about how
large a quantity may be, and the cache was the smaller one. One scale
and one precision for both.

Revision ID: a1c49683733c
Revises: smvmoved01
Create Date: 2026-08-30 20:39:02.842097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c49683733c'
down_revision: Union[str, None] = 'smvmoved01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'items',
        'quantity',
        existing_type=sa.Numeric(10, 3),
        type_=sa.Numeric(12, 3),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Values above 99,999,999.999 do not fit the old precision; they must
    # be cleaned before downgrading, which is why the cast is explicit.
    op.alter_column(
        'items',
        'quantity',
        existing_type=sa.Numeric(12, 3),
        type_=sa.Numeric(10, 3),
        existing_nullable=False,
        postgresql_using='quantity::numeric(10, 3)',
    )
