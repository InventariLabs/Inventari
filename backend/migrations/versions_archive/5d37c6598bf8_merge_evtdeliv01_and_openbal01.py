"""merge evtdeliv01 and openbal01

Revision ID: 5d37c6598bf8
Revises: evtdeliv01, openbal01
Create Date: 2026-09-24 19:35:06.825450

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d37c6598bf8'
down_revision: Union[str, None] = ('evtdeliv01', 'openbal01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
