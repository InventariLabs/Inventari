"""add_display_text_to_recipe_ingredients

Revision ID: 09ae07a47c69
Revises: e6f7a8b9c0d1
Create Date: 2026-04-06 12:19:33.127377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '09ae07a47c69'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('recipe_ingredients', sa.Column('display_text', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('recipe_ingredients', 'display_text')
