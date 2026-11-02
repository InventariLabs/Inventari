"""add short_id to household

Revision ID: 5f1a86550955
Revises: 7adcc6d3f1a3
Create Date: 2026-02-15 16:08:09.044039

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f1a86550955'
down_revision: Union[str, None] = '7adcc6d3f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('households', sa.Column('short_id', sa.String(20), nullable=True))
    op.create_index('ix_households_short_id', 'households', ['short_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_households_short_id', table_name='households')
    op.drop_column('households', 'short_id')
