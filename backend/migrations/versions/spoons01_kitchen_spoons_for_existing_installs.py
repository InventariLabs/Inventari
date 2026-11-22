"""add the tablespoon and the teaspoon where the kitchen measures already are

The food profile's seed now carries the two spoons, and a seed runs only when
an organization is onboarded or switches profile. An installation that took the
cups and the ounces earlier keeps twenty units, so the spoon conversions of
its ingredients, the AI parser's ``tbsp`` and ``tsp`` and the import review's
unit check have no unit to land on. This inserts the two rows into every
installation that already has the US cup, which is how the kitchen measures are
recognised, and leaves one that never took them alone.

A unit is matched by name, as the seed does, so one that someone added by hand
under the same name stays as it is. The reference unit of Volume, the
millilitre, is untouched.

Revision ID: spoons01
Revises: aicost01
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'spoons01'
down_revision: str | None = 'aicost01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SPOONS = (
    ('Tablespoon', 'tbsp', '14.7868'),
    ('Teaspoon', 'tsp', '4.92892'),
)


def upgrade() -> None:
    for name, symbol, factor in _SPOONS:
        op.execute(
            f"""
            INSERT INTO uoms
                (id, organization_id, category_id, name, symbol, factor,
                 is_reference, is_system, rounding)
            SELECT gen_random_uuid(), NULL, cup.category_id, '{name}',
                   '{symbol}', {factor}, false, true, 0.001
              FROM uoms cup
             WHERE cup.name = 'Cup (US)'
               AND cup.organization_id IS NULL
               AND NOT EXISTS (SELECT 1 FROM uoms WHERE name = '{name}')
             LIMIT 1
            """
        )


def downgrade() -> None:
    # A spoon may be on an ingredient or a recipe line by now; removing the
    # row would orphan them. No-op, by design.
    pass
