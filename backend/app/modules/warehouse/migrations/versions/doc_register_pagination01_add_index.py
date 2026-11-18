"""register pagination index: (organization_id, status, created_at).

Revision ID: doc_register_pagination01
Revises: doc_executed_location01
Create Date: 2026-08-29

The document register filters by organization, status and a date window,
then sorts by created_at. No index carries ``created_at`` beside those columns:
``ix_document_org_type_status`` and ``ix_document_org_partner`` both miss it, so
every page of rows sorts the whole matching set. Pagination alone would only
move that cost; this index lets Postgres walk the window in order.

Downgrade drops the index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'doc_register_pagination01'
down_revision: str | None = 'doc_executed_location01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'ix_document_org_status_created_at',
        'documents',
        ['organization_id', 'status', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_document_org_status_created_at', table_name='documents')
