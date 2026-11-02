"""add is_opening to documents.

Revision ID: doc_opening_stock01
Revises: doc_number_sequence01
Create Date: 2026-09-03

A receipt made from an opening-stock sheet is flagged so reports and the
partner rule can tell it from a purchase. Existing rows are purchases.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_opening_stock01'
down_revision: str | None = 'doc_number_sequence01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column(
            'is_opening',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('documents', 'is_opening')
