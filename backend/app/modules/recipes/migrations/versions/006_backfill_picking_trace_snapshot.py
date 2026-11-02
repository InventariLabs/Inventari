"""backfill the picking trace snapshot from the ingredients still attached

Sessions recorded before 005 have no snapshot. As long as their ingredient
still exists, what the recipe asked for can be reconstructed — name, the
servings-scaled quantity, and the unit symbol. Rows whose ingredient is
already gone cannot be recovered and stay blank.

Revision ID: 006_backfill_picking_trace
Revises: 005_picking_trace_snapshot
Create Date: 2026-08-20

"""

from collections.abc import Sequence

from alembic import op

revision: str = '006_backfill_picking_trace'
down_revision: str | None = '005_picking_trace_snapshot'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = """
UPDATE picking_session_items psi
SET ingredient_name = ri.name,
    required_quantity = ROUND(
        ri.quantity * (ps.servings::numeric / GREATEST(r.servings, 1)), 3
    ),
    required_uom_symbol = (SELECT u.symbol FROM uoms u WHERE u.id = ri.uom_id)
FROM recipe_ingredients ri, picking_sessions ps, recipes r
WHERE psi.ingredient_id = ri.id
  AND ps.id = psi.session_id
  AND r.id = ps.recipe_id
  AND psi.ingredient_name IS NULL
"""


def upgrade() -> None:
    op.execute(_BACKFILL)


def downgrade() -> None:
    # The snapshot columns go away in 005's downgrade; nothing to undo here.
    pass
