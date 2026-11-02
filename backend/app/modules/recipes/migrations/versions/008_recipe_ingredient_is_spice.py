"""the cook's spice mark: recipe_ingredients.is_spice

Revision ID: 008_recipe_ingredient_is_spice
Revises: 007_picking_session_scale
Create Date: 2026-10-04

The import review lets the cook mark an ingredient as a spice whatever its
amount says — one bay leaf is not a spice by weight. The mark had nowhere
to go and was dropped on save, so the card, which folds its seasonings
section from the amount, put the marked leaf back in the main list. The
column carries the mark with the recipe; rows written before it are not
spices they were never marked as.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '008_recipe_ingredient_is_spice'
down_revision: str | None = '007_picking_session_scale'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'recipe_ingredients',
        sa.Column(
            'is_spice',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # The model supplies the default; drop the server default to keep
    # the schema clean (matches 002_add_allergens and the rest of the table).
    op.alter_column('recipe_ingredients', 'is_spice', server_default=None)


def downgrade() -> None:
    op.drop_column('recipe_ingredients', 'is_spice')
