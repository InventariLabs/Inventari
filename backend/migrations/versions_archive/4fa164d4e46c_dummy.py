"""dummy

Revision ID: 4fa164d4e46c
Revises: 17660e6908be
Create Date: 2026-01-31 22:56:41.421136

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '4fa164d4e46c'
down_revision: Union[str, None] = '17660e6908be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
