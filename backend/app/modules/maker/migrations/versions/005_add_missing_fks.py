"""maker module — add missing FK constraints on recipe/uom columns.

Migration 003 added ``recipe_id`` / ``uom_id`` as plain UUID columns so the
data backfill could run before the constraints existed. The SQLAlchemy models
declare foreign keys for these columns, so a database migrated via alembic
drifts from the model. This migration adds the three missing constraints:

- ``maker_bom_lines.recipe_id`` → ``maker_recipes.id`` (ON DELETE CASCADE)
- ``maker_bom_lines.uom_id`` → ``uoms.id``
- ``maker_production_orders.recipe_id`` → ``maker_recipes.id``

Constraint names follow the SQLAlchemy default convention
(``<table>_<column>_fkey``) because ``Base`` defines no naming convention —
these are exactly the names a fresh ``create_all`` from the models produces.

``maker_recipes.source_recipe_id`` intentionally stays FK-less (soft,
audit-only cross-module reference — see models.py).

Revision ID: 005_add_missing_fks
Revises: 004_module_settings
Create Date: 2026-08-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = '005_add_missing_fks'
down_revision: str | None = '004_module_settings'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        'maker_bom_lines_recipe_id_fkey',
        'maker_bom_lines',
        'maker_recipes',
        ['recipe_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'maker_bom_lines_uom_id_fkey',
        'maker_bom_lines',
        'uoms',
        ['uom_id'],
        ['id'],
    )
    op.create_foreign_key(
        'maker_production_orders_recipe_id_fkey',
        'maker_production_orders',
        'maker_recipes',
        ['recipe_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'maker_production_orders_recipe_id_fkey',
        'maker_production_orders',
        type_='foreignkey',
    )
    op.drop_constraint(
        'maker_bom_lines_uom_id_fkey',
        'maker_bom_lines',
        type_='foreignkey',
    )
    op.drop_constraint(
        'maker_bom_lines_recipe_id_fkey',
        'maker_bom_lines',
        type_='foreignkey',
    )
