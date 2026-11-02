"""maker module — a recipe cost line always has its place in the list.

``maker_recipe_cost_lines.sort_order`` was created nullable with a server
default of 0, while the model declares it ``NOT NULL``. Autogenerate read the
difference as a change to make on every database. Rows written without the
column already hold 0; any NULL left by a direct insert becomes 0 too.

Revision ID: 013_sort_order_not_null
Revises: 012_timestamps_carry_their_zone
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '013_sort_order_not_null'
down_revision: str | None = '012_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        'UPDATE maker_recipe_cost_lines SET sort_order = 0 WHERE sort_order IS NULL'
    )
    op.alter_column(
        'maker_recipe_cost_lines',
        'sort_order',
        existing_type=sa.Integer(),
        nullable=False,
        existing_server_default=sa.text('0'),
    )


def downgrade() -> None:
    op.alter_column(
        'maker_recipe_cost_lines',
        'sort_order',
        existing_type=sa.Integer(),
        nullable=True,
        existing_server_default=sa.text('0'),
    )
