"""add_completed_by_transit_scrap_fk_item_history

Revision ID: 2fc067ab6978
Revises: 8273d8983734
Create Date: 2026-04-12 20:35:57.172837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fc067ab6978'
down_revision: Union[str, None] = '8273d8983734'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('completed_by', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_documents_completed_by_users',
        'documents', 'users',
        ['completed_by'], ['id'],
        ondelete='SET NULL',
    )
    # Clean orphaned references before adding FK
    op.execute("""
        UPDATE item_history SET source_document_id = NULL
        WHERE source_document_id IS NOT NULL
        AND source_document_id NOT IN (SELECT id FROM documents)
    """)
    op.create_foreign_key(
        'fk_item_history_source_document_id',
        'item_history', 'documents',
        ['source_document_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_item_history_source_document_id', 'item_history', type_='foreignkey')
    op.drop_constraint('fk_documents_completed_by_users', 'documents', type_='foreignkey')
    op.drop_column('documents', 'completed_by')
