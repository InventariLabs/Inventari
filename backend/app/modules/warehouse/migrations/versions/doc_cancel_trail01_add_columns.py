"""add cancelled_by and cancelled_at to documents.

Revision ID: doc_cancel_trail01
Revises: doc_stock_applied01
Create Date: 2026-10-03

Cancelling a document was the one transition that named nobody: the row
kept no canceller and no time, so a withdrawal three months old had no
author. The two columns carry what the card shows and the log entry says.

Downgrade drops the columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_cancel_trail01'
down_revision: str | None = 'doc_stock_applied01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column(
            'cancelled_by',
            sa.UUID(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column(
        'documents',
        sa.Column(
            'cancelled_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('documents', 'cancelled_at')
    op.drop_column('documents', 'cancelled_by')
