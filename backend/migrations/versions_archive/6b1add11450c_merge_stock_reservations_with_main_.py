"""merge stock_reservations with main branch

Revision ID: 6b1add11450c
Revises: a1b2c3d4e5f6, e3ffe1ea0d75
Create Date: 2026-06-14 19:23:50.799996

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b1add11450c'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', 'e3ffe1ea0d75')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
