"""a picking session remembers the meal-plan entry it was started from

Revision ID: 012_picking_session_plan_entry
Revises: 011_image_url_keeps_the_key
Create Date: 2026-10-25

A recipe planned twice in one day (lunch and dinner) gave the plan no way to
tell which card was cooked: the finished session knew only its recipe and the
day, so the plan marked whichever entry sorted first. ``meal_plan_entry_id``
records the card Cook Now was pressed on; the plan marks that entry. A session
started from the recipe page leaves it NULL and is attributed by the day it
finished, as before, so there is nothing to backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '012_picking_session_plan_entry'
down_revision: str | None = '011_image_url_keeps_the_key'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'picking_sessions',
        sa.Column('meal_plan_entry_id', sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        'fk_picking_sessions_meal_plan_entry_id',
        'picking_sessions',
        'meal_plan_entries',
        ['meal_plan_entry_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_picking_sessions_meal_plan_entry_id',
        'picking_sessions',
        ['meal_plan_entry_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_picking_sessions_meal_plan_entry_id', 'picking_sessions')
    op.drop_constraint(
        'fk_picking_sessions_meal_plan_entry_id', 'picking_sessions', type_='foreignkey'
    )
    op.drop_column('picking_sessions', 'meal_plan_entry_id')
