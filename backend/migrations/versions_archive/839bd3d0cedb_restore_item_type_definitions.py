"""Restore item_type_definitions

Revision ID: 839bd3d0cedb
Revises: 584923bfd21e
Create Date: 2026-02-12 23:45:17.197895

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '839bd3d0cedb'
down_revision: Union[str, None] = '584923bfd21e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
