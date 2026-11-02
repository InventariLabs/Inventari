"""add the date of the stock a pick line plans to take.

Revision ID: doc_pick_line_expiry01
Revises: doc_source_shelf01
Create Date: 2026-10-19

``wms_pick_lines.expiry_date`` is the date the picker reads next to the
batch: the batch's, or, for stock with no batch, the date of the record the
draw takes first.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_pick_line_expiry01'
down_revision: str | None = 'doc_source_shelf01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('wms_pick_lines', sa.Column('expiry_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('wms_pick_lines', 'expiry_date')
