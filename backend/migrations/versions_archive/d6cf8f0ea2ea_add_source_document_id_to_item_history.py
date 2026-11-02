"""add_source_document_id_to_item_history

Revision ID: d6cf8f0ea2ea
Revises: 7b9dca2f558d
Create Date: 2026-03-18 20:02:31.581448

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd6cf8f0ea2ea'
down_revision: Union[str, None] = '7b9dca2f558d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'item_history',
        sa.Column('source_document_id', sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f('ix_item_history_source_document_id'),
        'item_history',
        ['source_document_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_item_history_source_document_id'),
        table_name='item_history',
    )
    op.drop_column('item_history', 'source_document_id')
