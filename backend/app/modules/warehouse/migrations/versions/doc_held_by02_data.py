"""name the approvals module on the documents waiting for an approval.

Revision ID: doc_held_by02
Revises: doc_held_by01
Create Date: 2026-10-23

Until ``held_by`` existed the approvals module was the only one that ever
parked a document in PENDING_APPROVAL, so every document found there waits
for it.

Downgrade empties the column; the schema downgrade drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_held_by02'
down_revision: str | None = 'doc_held_by01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE documents SET held_by = 'approvals' "
            "WHERE status = 'PENDING_APPROVAL' AND held_by IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text('UPDATE documents SET held_by = NULL'))
