"""timestamps carry their zone: convert the naive recipes columns to timestamptz

Revision ID: 009_timestamps_carry_their_zone
Revises: 008_recipe_ingredient_is_spice
Create Date: 2026-10-10

A database that grew through the migration chain before it was flattened
holds many timestamp columns as ``timestamp without time zone`` while the
models declare ``DateTime(timezone=True)``: the API then sends those times
without an offset and the browser shows them shifted by the reader's UTC
offset, and a Python comparison against an aware ``now`` raises
``TypeError``. The core chain's ``tzaware01`` explains it in full; this
revision converts this module's tables. Stored values are read as UTC; a
column that is already aware is left alone, so a database built from the
current chain sees no change.

Downgrade leaves the columns aware.
"""

from collections.abc import Sequence

from app.core.migration_helpers import convert_naive_timestamps_to_utc

revision: str = '009_timestamps_carry_their_zone'
down_revision: str | None = '008_recipe_ingredient_is_spice'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every column the models declare ``DateTime(timezone=True)``, frozen as of
#: this revision.
_AWARE_COLUMNS: dict[str, tuple[str, ...]] = {
    'ingredient_nutrition_defaults': ('created_at', 'updated_at'),
    'meal_plans': ('created_at', 'updated_at'),
    'picking_sessions': ('created_at', 'completed_at'),
    'recipe_collection_members': ('created_at',),
    'recipe_collections': ('created_at',),
    'recipe_tag_configs': ('created_at',),
    'recipes': ('created_at', 'updated_at'),
    'shopping_exclusions': ('created_at', 'updated_at'),
}


def upgrade() -> None:
    convert_naive_timestamps_to_utc(_AWARE_COLUMNS)


def downgrade() -> None:
    # Nothing to restore: the naive type was the defect, and on a database
    # that was aware all along there is nothing to undo. Turning the columns
    # back would bring the shifted times back with them.
    pass
