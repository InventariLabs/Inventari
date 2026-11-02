"""add blind_mode and tolerance_percent to stock_takes

Revision ID: 85ac21ffa939
Revises: 9b37c1edc8ab
Create Date: 2026-04-27 12:21:33.698422

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '85ac21ffa939'
down_revision: Union[str, None] = '9b37c1edc8ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_takes', sa.Column(
        'blind_mode', sa.Boolean(), nullable=False, server_default=sa.text('false')
    ))
    op.add_column('stock_takes', sa.Column(
        'tolerance_percent', sa.Numeric(precision=5, scale=2), nullable=True
    ))


def downgrade() -> None:
    op.drop_column('stock_takes', 'tolerance_percent')
    op.drop_column('stock_takes', 'blind_mode')
