"""add_backorder_id_to_documents

Revision ID: 1b7a160cceb7
Revises: 2fc067ab6978
Create Date: 2026-04-12 20:44:57.745356

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b7a160cceb7'
down_revision: Union[str, None] = '2fc067ab6978'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('backorder_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_documents_backorder_id'), 'documents', ['backorder_id'], unique=False)
    op.create_foreign_key(
        'fk_documents_backorder_id',
        'documents', 'documents',
        ['backorder_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_documents_backorder_id', 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_documents_backorder_id'), table_name='documents')
    op.drop_column('documents', 'backorder_id')
