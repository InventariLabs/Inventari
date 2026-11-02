"""add meta_data to documents and document_lines.

Revision ID: doc_meta_data01
Revises: doc_held_by02
Create Date: 2026-10-23

A module built for one customer needs a field of its own on a document or a
line — a certificate number, a customs code — and had nowhere to keep it:
another module's table takes no foreign columns. Both tables gain the same
namespaced JSONB an item has, one key per module. Existing rows carry none.

Downgrade drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'doc_meta_data01'
down_revision: str | None = 'doc_held_by02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'documents', sa.Column('meta_data', postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        'document_lines', sa.Column('meta_data', postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('document_lines', 'meta_data')
    op.drop_column('documents', 'meta_data')
