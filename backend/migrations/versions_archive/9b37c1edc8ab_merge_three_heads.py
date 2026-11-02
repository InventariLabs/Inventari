"""merge_three_heads

Revision ID: 9b37c1edc8ab
Revises: 3e84b62c8749, 5b8c0d4e6f7a, a1e2f3a4b5c6
Create Date: 2026-04-26 22:06:10.080025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b37c1edc8ab'
down_revision: Union[str, None] = ('3e84b62c8749', '5b8c0d4e6f7a', 'a1e2f3a4b5c6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
