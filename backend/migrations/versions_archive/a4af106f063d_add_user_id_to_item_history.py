"""add_user_id_to_item_history

Revision ID: a4af106f063d
Revises: b08b4ee4b477
Create Date: 2026-02-15 17:58:31.111662

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4af106f063d'
down_revision: Union[str, None] = 'b08b4ee4b477'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.add_column('item_history', sa.Column('user_id', sa.Uuid(), nullable=True))
        op.create_foreign_key('fk_item_history_user', 'item_history', 'users', ['user_id'], ['id'], ondelete='SET NULL')
        op.create_index(op.f('ix_item_history_user_id'), 'item_history', ['user_id'], unique=False)
    except Exception:
        pass


def downgrade() -> None:
    pass
