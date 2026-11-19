"""maker module — the day a completed run was planned for.

A run closed on another day than the one it was planned for keeps its plan
in ``planned_for``; ``production_date`` then holds the day it was made.

Revision ID: 022_planned_for
Revises: 021_label_facts
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '022_planned_for'
down_revision: str | None = '021_label_facts'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_orders',
        sa.Column('planned_for', sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('maker_production_orders', 'planned_for')
