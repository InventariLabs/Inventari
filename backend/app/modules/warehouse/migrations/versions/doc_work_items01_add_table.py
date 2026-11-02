"""add document_work_item_overlays for assignees and custom tasks.

Revision ID: doc_work_items01
Revises: doc_session_activity01
Create Date: 2026-10-19

To do is read from the records that ask for work. What cannot be read from
them is kept here: the person a derived task is assigned to, and the tasks
the boss adds by hand (title, assignee, due date, done).

Downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_work_items01'
down_revision: str | None = 'doc_session_activity01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'document_work_item_overlays',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('source_kind', sa.String(48), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column(
            'assignee_id',
            sa.UUID(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_by',
            sa.UUID(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        'ix_document_work_item_overlays_organization_id',
        'document_work_item_overlays',
        ['organization_id'],
    )
    op.create_index(
        'uq_document_work_item_overlays_source',
        'document_work_item_overlays',
        ['organization_id', 'source_kind', 'source_id'],
        unique=True,
        postgresql_where=sa.text('source_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_document_work_item_overlays_source', 'document_work_item_overlays'
    )
    op.drop_index(
        'ix_document_work_item_overlays_organization_id',
        'document_work_item_overlays',
    )
    op.drop_table('document_work_item_overlays')
