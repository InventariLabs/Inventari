"""add_index_picking_session_user_id

Revision ID: dba3438c9c01
Revises: 22f8e1551ea7
Create Date: 2026-03-07 22:38:36.192207

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'dba3438c9c01'
down_revision: Union[str, None] = '22f8e1551ea7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_picking_sessions_user_id',
        'picking_sessions',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_picking_sessions_user_id', table_name='picking_sessions')
