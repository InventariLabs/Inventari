"""add_item_attachments

Revision ID: 0bda189c2c75
Revises: c7dbe1cb6a45
Create Date: 2026-02-12 18:09:21.953672

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0bda189c2c75'
down_revision: Union[str, None] = 'c7dbe1cb6a45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('item_attachments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('item_id', sa.Uuid(), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_item_attachments_item_id'), 'item_attachments', ['item_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_item_attachments_item_id'), table_name='item_attachments')
    op.drop_table('item_attachments')
