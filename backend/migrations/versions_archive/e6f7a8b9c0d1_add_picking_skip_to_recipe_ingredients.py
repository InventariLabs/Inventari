"""add picking_skip to recipe_ingredients

Adds a tri-state override flag for picking session behaviour:
  NULL  = use heuristic (qty/uom-based auto-skip)
  TRUE  = always skip this ingredient in picking
  FALSE = always pick this ingredient (overrides heuristic)

Revision ID: e6f7a8b9c0d1
Revises: f3a1b2c4d5e6
Create Date: 2026-04-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: str = 'f3a1b2c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'recipe_ingredients',
        sa.Column('picking_skip', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('recipe_ingredients', 'picking_skip')
