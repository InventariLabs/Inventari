"""Add discrepancy_reason_code to stock_take_items.

Revision ID: 003_discrepancy_reason_code
Revises: 002_set_null_item_fk
Create Date: 2026-08-31

A count that finds less than the system holds is only half an answer. The
other half — breakage, expiry, loss, a miscount, goods on the wrong shelf —
lived in a free-text column that no report could add up. This puts a short
code beside the note: the code is countable across counts, the note says
what the code cannot.

Existing rows keep NULL: whatever they say is the note, and nobody is going
to guess a code for it after the fact.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '003_discrepancy_reason_code'
down_revision: str | None = '002_set_null_item_fk'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_take_items',
        sa.Column('discrepancy_reason_code', sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('stock_take_items', 'discrepancy_reason_code')
