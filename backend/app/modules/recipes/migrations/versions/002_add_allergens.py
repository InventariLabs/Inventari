"""add allergens to recipe_ingredients

Adds the ``allergens`` JSONB column (EU 1169/2011 keys, see
``app.modules.recipes._allergens``) to ``recipe_ingredients``.

Revision ID: 002_add_allergens
Revises: 001_initial
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '002_add_allergens'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'recipe_ingredients',
        sa.Column(
            'allergens',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # The model supplies the default; drop the server default to keep
    # the schema clean (matches the rest of the table).
    op.alter_column('recipe_ingredients', 'allergens', server_default=None)


def downgrade() -> None:
    op.drop_column('recipe_ingredients', 'allergens')
