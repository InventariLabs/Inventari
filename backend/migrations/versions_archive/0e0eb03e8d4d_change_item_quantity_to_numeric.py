"""change_item_quantity_to_numeric

Revision ID: 0e0eb03e8d4d
Revises: add_storage_type_fields
Create Date: 2026-01-29 18:32:14.096880

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e0eb03e8d4d'
down_revision: Union[str, None] = 'add_storage_type_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('items', 'quantity',
               existing_type=sa.INTEGER(),
               type_=sa.Numeric(precision=10, scale=3),
               existing_nullable=True,
               postgresql_using='quantity::numeric')


def downgrade() -> None:
    op.alter_column('items', 'quantity',
               existing_type=sa.Numeric(precision=10, scale=3),
               type_=sa.INTEGER(),
               existing_nullable=True,
               postgresql_using='quantity::integer')
