"""merge wms_pick branch with trigram branch

Revision ID: e5f6a7b8c9d0
Revises: a1b2c3d4e5f6, d4e5f6a7b8c9
Create Date: 2026-04-22 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
