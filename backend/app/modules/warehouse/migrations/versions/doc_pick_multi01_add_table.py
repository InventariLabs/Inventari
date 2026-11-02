"""create wms_pick_session_documents table (one picking session, several dispatches).

Revision ID: doc_pick_multi01
Revises: doc_confirm_shelf01
Create Date: 2026-10-17

A picking session can now walk several confirmed dispatches at once. The
session keeps ``document_id`` as its first document, so every reader of that
column keeps its answer; this table lists all of the session's documents in
the order they were asked for. Existing sessions get no rows: a session with
none is the session of its ``document_id`` alone.

Downgrade drops the table; sessions over several documents then read as
sessions of their first one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_pick_multi01'
down_revision: str | None = 'doc_confirm_shelf01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'wms_pick_session_documents',
        sa.Column(
            'session_id',
            sa.UUID(),
            sa.ForeignKey('wms_pick_sessions.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column(
            'document_id',
            sa.UUID(),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column('position', sa.Integer(), nullable=False),
    )
    op.create_index(
        'ix_wms_pick_session_documents_document_id',
        'wms_pick_session_documents',
        ['document_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_wms_pick_session_documents_document_id',
        table_name='wms_pick_session_documents',
    )
    op.drop_table('wms_pick_session_documents')
