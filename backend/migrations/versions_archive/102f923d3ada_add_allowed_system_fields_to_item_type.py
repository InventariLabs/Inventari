"""add_allowed_system_fields_to_item_type

Revision ID: 102f923d3ada
Revises: 61cd3401e220
Create Date: 2026-02-11 23:33:05.373128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '102f923d3ada'
down_revision: Union[str, None] = '61cd3401e220'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("item_type_definitions", sa.Column("allowed_system_fields", sa.JSON(), server_default="[\"brand\", \"barcode\", \"quantity\", \"unit\", \"expiry_date\"]", nullable=False))


def downgrade() -> None:
    op.drop_column("item_type_definitions", "allowed_system_fields")


