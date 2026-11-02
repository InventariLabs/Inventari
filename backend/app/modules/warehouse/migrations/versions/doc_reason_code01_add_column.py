"""add reason_code to documents.

Revision ID: doc_reason_code01
Revises: doc_drop_allowed_fields01
Create Date: 2026-08-24

Corrections and returns recorded their reason as free text, so the question
"why do we correct documents" could only be answered by reading sentences.
This adds a short code alongside the note: the code is countable, the note
says what the code cannot.

Existing rows keep NULL — their reason is whatever the note says.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_reason_code01'
down_revision: str | None = 'doc_drop_allowed_fields01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('reason_code', sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('documents', 'reason_code')
