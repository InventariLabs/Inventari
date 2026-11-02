"""merge avcosnap01 and poorguniq01 heads

Revision ID: b0b06a800abb
Revises: avcosnap01, poorguniq01
Create Date: 2026-06-20 10:14:22.420251

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0b06a800abb'
down_revision: Union[str, None] = ('avcosnap01', 'poorguniq01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
