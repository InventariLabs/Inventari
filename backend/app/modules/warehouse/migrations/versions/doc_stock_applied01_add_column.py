"""add stock_already_applied to documents.

Revision ID: doc_stock_applied01
Revises: doc_pick_quant_gone01
Create Date: 2026-10-02

The RW document a picking session registers is the register's copy of a
movement the session already made. The flag tells confirmation and completion
to leave the shelves alone. Existing rows are ordinary documents.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_stock_applied01'
down_revision: str | None = 'doc_pick_quant_gone01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column(
            'stock_already_applied',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('documents', 'stock_already_applied')
