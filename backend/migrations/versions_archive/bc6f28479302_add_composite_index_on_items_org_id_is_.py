"""add composite index on items org_id is_deleted

Revision ID: bc6f28479302
Revises: f59d771c2f58
Create Date: 2026-05-05 07:13:05.043126

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'bc6f28479302'
down_revision: Union[str, None] = 'f59d771c2f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_items_org_not_deleted', 'items', ['organization_id', 'is_deleted'])


def downgrade() -> None:
    op.drop_index('ix_items_org_not_deleted', table_name='items')
