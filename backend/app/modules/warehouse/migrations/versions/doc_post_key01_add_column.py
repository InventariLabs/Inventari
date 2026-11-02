"""add post_key to documents.

Revision ID: doc_post_key01
Revises: doc_receiving01
Create Date: 2026-10-21

The one-screen actions create and post a document in one call. A press that
is sent twice — a double click, a retry after the answer was lost on the way
back — would create and post two documents. The screen now sends a key with
each press and the server remembers it on the document it made, so a repeat
of the same press is answered with that document instead of a second one.
Existing rows carry no key.

Downgrade drops the index and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_post_key01'
down_revision: str | None = 'doc_receiving01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('post_key', sa.String(64), nullable=True))
    op.create_index(
        'uq_document_org_post_key',
        'documents',
        ['organization_id', 'post_key'],
        unique=True,
        postgresql_where=sa.text('post_key IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_document_org_post_key', table_name='documents')
    op.drop_column('documents', 'post_key')
