"""drop_legacy_unit_columns

Revision ID: 9f479e121c3a
Revises: 951489f76322
Create Date: 2026-04-11 21:08:06.732414

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f479e121c3a'
down_revision: Union[str, None] = '951489f76322'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('document_lines', 'unit')
    op.drop_column('items', 'unit')
    op.drop_column('shopping_list_items', 'unit')
    op.drop_column('stock_take_items', 'item_unit')


def downgrade() -> None:
    op.add_column('stock_take_items', sa.Column('item_unit', sa.VARCHAR(length=50), autoincrement=False, nullable=True))
    op.add_column('shopping_list_items', sa.Column('unit', sa.VARCHAR(length=50), autoincrement=False, nullable=True))
    op.add_column('items', sa.Column('unit', sa.VARCHAR(length=50), autoincrement=False, nullable=True))
    op.add_column('document_lines', sa.Column('unit', sa.VARCHAR(length=20), autoincrement=False, nullable=False))
