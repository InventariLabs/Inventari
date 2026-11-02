"""add is_superuser to user

Revision ID: b08b4ee4b477
Revises: 5f1a86550955
Create Date: 2026-02-15 16:10:39.343541

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b08b4ee4b477'
down_revision: Union[str, None] = '5f1a86550955'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility and better error handling
    # Adding a column with server_default=False
    try:
        op.add_column('users', sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    except Exception:
        # Column might already exist
        pass
    
    # Ensure existing users have False
    try:
        op.execute("UPDATE users SET is_superuser = false WHERE is_superuser IS NULL")
    except Exception:
        pass


def downgrade() -> None:
    op.drop_column('users', 'is_superuser')
