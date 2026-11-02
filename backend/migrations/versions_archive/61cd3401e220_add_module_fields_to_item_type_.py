"""Add module fields to item_type_definitions

Revision ID: 61cd3401e220
Revises: f7b8c9d1e2a3
Create Date: 2026-02-11 19:06:38.362201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61cd3401e220'
down_revision: Union[str, None] = 'f7b8c9d1e2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("item_type_definitions", sa.Column("module_name", sa.String(length=50), nullable=True))
    op.add_column("item_type_definitions", sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("item_type_definitions", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))
    op.create_index(op.f("ix_item_type_definitions_module_name"), "item_type_definitions", ["module_name"], unique=False)
    op.create_index(op.f("ix_item_type_definitions_is_active"), "item_type_definitions", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_item_type_definitions_is_active"), table_name="item_type_definitions")
    op.drop_index(op.f("ix_item_type_definitions_module_name"), table_name="item_type_definitions")
    op.drop_column("item_type_definitions", "is_active")
    op.drop_column("item_type_definitions", "is_system")
    op.drop_column("item_type_definitions", "module_name")
