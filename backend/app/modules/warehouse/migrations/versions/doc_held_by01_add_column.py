"""add held_by to documents.

Revision ID: doc_held_by01
Revises: doc_post_key01
Create Date: 2026-10-23

A document waiting in PENDING_APPROVAL was parked there by the warehouse
module calling the approvals module itself. The approval gate is now a
pre-post check the approvals module registers, and any module's check may
hold a document the same way. The column names the module the document waits
for, so only that module releases it and a hold of a module switched off for
the organization stands down. Empty on every document nothing holds.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_held_by01'
down_revision: str | None = 'doc_post_key01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('held_by', sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'held_by')
