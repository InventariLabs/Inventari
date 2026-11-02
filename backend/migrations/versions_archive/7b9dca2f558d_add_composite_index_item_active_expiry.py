"""add composite index item active expiry

Revision ID: 7b9dca2f558d
Revises: ad16661b8959
Create Date: 2026-03-17 23:34:50.542581

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7b9dca2f558d'
down_revision: Union[str, None] = 'ad16661b8959'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'idx_item_active_expiry',
        'items',
        ['is_deleted', 'expiry_date'],
    )


def downgrade() -> None:
    op.drop_index('idx_item_active_expiry', table_name='items')
