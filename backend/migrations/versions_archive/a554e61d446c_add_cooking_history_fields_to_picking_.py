"""add cooking history fields to picking session

Revision ID: a554e61d446c
Revises: dba3438c9c01
Create Date: 2026-03-07 23:14:49

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a554e61d446c'
down_revision: Union[str, None] = 'dba3438c9c01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('picking_sessions', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('picking_sessions', sa.Column('rating', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('picking_sessions', 'rating')
    op.drop_column('picking_sessions', 'notes')
