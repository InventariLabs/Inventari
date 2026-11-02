"""a meal plan keeps the meals its shopping list was generated from

Revision ID: 013_meal_plan_listed_meals
Revises: 012_picking_session_plan_entry
Create Date: 2026-10-31

The plan screen said "Meals added after the list was generated are not on it
yet." under every generated list, whether or not anything had been planned
since — a standing line nobody can act on. ``listed_meals`` records, at each
generation, the meals the list was made from (recipe and servings), and the
plan compares the meals it holds now against them: the sentence stands only
while a meal is planned that the list was not made for, and goes when that
meal is taken off again. Existing plans start at NULL: nothing records what
their list was made from, and filling the column from the meals they hold
today would claim that every meal planned since the list was made is on it.
A listed plan at NULL is read as a list the plan cannot vouch for — the
screen offers the refresh, as it did before, and the refresh records the
meals.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '013_meal_plan_listed_meals'
down_revision: str | None = '012_picking_session_plan_entry'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'meal_plans',
        sa.Column('listed_meals', postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('meal_plans', 'listed_meals')
