"""add failed_login_count and locked_until to users

Revision ID: cd81ebba893d
Revises: 0a010f3ac3fb
Create Date: 2026-05-10 21:29:42.101580

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'cd81ebba893d'
down_revision: Union[str, None] = '0a010f3ac3fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('failed_login_count', sa.BigInteger(), server_default='0', nullable=True),
    )
    op.add_column(
        'users',
        sa.Column('locked_until', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_count')
