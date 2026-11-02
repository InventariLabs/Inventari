"""add_household_id_to_items_and_history

Revision ID: d473d077732f
Revises: e5cca324c35e
Create Date: 2026-02-16 19:54:09.583871

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd473d077732f'
down_revision: Union[str, None] = 'e5cca324c35e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('items', sa.Column('household_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(None, 'items', 'households', ['household_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_items_household_id'), 'items', ['household_id'], unique=False)

    op.add_column('item_history', sa.Column('household_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(None, 'item_history', 'households', ['household_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_item_history_household_id'), 'item_history', ['household_id'], unique=False)


def downgrade() -> None:
    op.drop_constraint('item_history_household_id_fkey', 'item_history', type_='foreignkey')
    op.drop_index(op.f('ix_item_history_household_id'), table_name='item_history')
    op.drop_column('item_history', 'household_id')

    op.drop_constraint('items_household_id_fkey', 'items', type_='foreignkey')
    op.drop_index(op.f('ix_items_household_id'), table_name='items')
    op.drop_column('items', 'household_id')
