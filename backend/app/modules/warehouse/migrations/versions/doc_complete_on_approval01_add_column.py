"""add complete_on_approval to documents.

Revision ID: doc_complete_on_approval01
Revises: doc_work_items01
Create Date: 2026-10-19

The one-step action confirms and completes a document in one transaction.
Where the profile demands an approval it can only do the first half: the
document waits in PENDING_APPROVAL. This flag records the half the action
still owes, so the approval that releases the document completes it instead
of leaving the reader to press a second button. Existing rows came through
the two-step path and stay false.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_complete_on_approval01'
down_revision: str | None = 'doc_work_items01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column(
            'complete_on_approval',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('documents', 'complete_on_approval')
