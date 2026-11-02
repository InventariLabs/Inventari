"""the movement names the date of the goods it took: stock_moves.expiry_date

Revision ID: moveexpiry01
Revises: catfefo01
Create Date: 2026-10-19

A pack received with a date but no batch number is a record carrying the
date itself, and FEFO draws by it. The movement of such a draw named the
shelf and the quantity and nothing that told one dated record from the
next, so the ledger could not say which date left.

No backfill: the records a past draw took are gone, and the date of a
batch is already readable through the batch. Rows before this change
carry no date of their own, which is what they know.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'moveexpiry01'
down_revision: str | None = 'catfefo01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('stock_moves', sa.Column('expiry_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_moves', 'expiry_date')
