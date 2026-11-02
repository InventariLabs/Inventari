"""merge all heads

Revision ID: a46daee2e1d5
Revises: 69ce931ccd7a, a1b2c3d4e5f6, a7f8c9d0e1b2, f7b8c9d1e2a3
Create Date: 2026-04-27 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a46daee2e1d5'
down_revision: Union[str, None] = ('69ce931ccd7a', 'a1b2c3d4e5f6', 'a7f8c9d0e1b2', 'f7b8c9d1e2a3', 'f282f66d15d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
