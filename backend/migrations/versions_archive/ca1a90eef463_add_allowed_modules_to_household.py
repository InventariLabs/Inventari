"""add_allowed_modules_to_household

Revision ID: ca1a90eef463
Revises: a4af106f063d
Create Date: 2026-02-15 18:15:37.088983

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca1a90eef463'
down_revision: Union[str, None] = 'a4af106f063d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.add_column('households', sa.Column('allowed_modules', sa.JSON(), nullable=True))
    except Exception:
        # Column might already exist if stamp was used incorrectly
        pass
    # By default, we could initialize it with something, but null is fine if we handle it in code.


def downgrade() -> None:
    pass
