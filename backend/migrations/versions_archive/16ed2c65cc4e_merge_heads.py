"""merge_heads

Revision ID: 16ed2c65cc4e
Revises: dff9037cf1f3, z_add_active_assignment_uc
Create Date: 2026-05-29 08:39:21.381675

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16ed2c65cc4e'
down_revision: Union[str, None] = ('dff9037cf1f3', 'z_add_active_assignment_uc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
