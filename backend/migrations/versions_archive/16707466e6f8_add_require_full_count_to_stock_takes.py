"""add require_full_count to stock_takes

Revision ID: 16707466e6f8
Revises: 85ac21ffa939
Create Date: 2026-04-27 14:46:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '16707466e6f8'
down_revision: Union[str, None] = '85ac21ffa939'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_takes', sa.Column(
        'require_full_count', sa.Boolean(), nullable=False, server_default=sa.text('true')
    ))


def downgrade() -> None:
    op.drop_column('stock_takes', 'require_full_count')
