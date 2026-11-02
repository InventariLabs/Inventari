"""add original_quantity and original_unit_text to recipe_ingredients

Revision ID: 3d49c70da606
Revises: 09ae07a47c69
Create Date: 2026-04-06 16:25:45.688623

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d49c70da606'
down_revision: Union[str, None] = '09ae07a47c69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('recipe_ingredients', sa.Column('original_quantity', sa.Numeric(precision=10, scale=3), nullable=True))
    op.add_column('recipe_ingredients', sa.Column('original_unit_text', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('recipe_ingredients', 'original_unit_text')
    op.drop_column('recipe_ingredients', 'original_quantity')
