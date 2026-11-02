"""detach picking session items from deleted ingredients and snapshot what was asked

A completed picking session is an accounting record: it holds what left the
shelf, at which AVCO rate, and from which items. It hung off
``recipe_ingredients`` through ON DELETE CASCADE, so removing an ingredient —
or any save that replaced the ingredient list — erased it.

The FK becomes ON DELETE SET NULL and the row carries a snapshot of what the
recipe asked for, so the trace stays readable after the ingredient is gone.

Revision ID: 005_picking_trace_snapshot
Revises: 004_recipe_collections
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '005_picking_trace_snapshot'
down_revision: str | None = '004_recipe_collections'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = 'picking_session_items_ingredient_id_fkey'


def upgrade() -> None:
    op.add_column(
        'picking_session_items',
        sa.Column('ingredient_name', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'picking_session_items',
        sa.Column('required_quantity', sa.Numeric(10, 3), nullable=True),
    )
    op.add_column(
        'picking_session_items',
        sa.Column('required_uom_symbol', sa.String(length=10), nullable=True),
    )
    op.alter_column(
        'picking_session_items',
        'ingredient_id',
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.drop_constraint(_FK, 'picking_session_items', type_='foreignkey')
    op.create_foreign_key(
        _FK,
        'picking_session_items',
        'recipe_ingredients',
        ['ingredient_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # Rows already detached have no ingredient to point back at; they cannot
    # survive a NOT NULL column, so they go.
    op.execute(
        'DELETE FROM picking_session_items WHERE ingredient_id IS NULL'  # noqa: S608
    )
    op.drop_constraint(_FK, 'picking_session_items', type_='foreignkey')
    op.create_foreign_key(
        _FK,
        'picking_session_items',
        'recipe_ingredients',
        ['ingredient_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.alter_column(
        'picking_session_items',
        'ingredient_id',
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_column('picking_session_items', 'required_uom_symbol')
    op.drop_column('picking_session_items', 'required_quantity')
    op.drop_column('picking_session_items', 'ingredient_name')
