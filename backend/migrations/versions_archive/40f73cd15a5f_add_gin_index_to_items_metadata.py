"""add_gin_index_to_items_metadata

Revision ID: 40f73cd15a5f
Revises: c66bab90f036
Create Date: 2026-02-12 19:16:45.567373

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40f73cd15a5f'
down_revision: Union[str, None] = 'c66bab90f036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_items_meta_data_gin",
        "items",
        ["meta_data"],
        postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_items_meta_data_gin", table_name="items")
