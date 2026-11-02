"""add_recipes_module

Revision ID: a1b2c3d4e5f6
Revises: 08e019e9a79b
Create Date: 2026-03-07 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '22f8e1551ea7'
down_revision: Union[str, None] = '08e019e9a79b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- recipes ---
    op.create_table(
        'recipes',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.Uuid(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('servings', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('prep_time_minutes', sa.Integer(), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_recipes_organization_id', 'recipes', ['organization_id'])
    op.create_index('ix_recipes_organization_id_is_favorite', 'recipes', ['organization_id', 'is_favorite'])

    # --- recipe_ingredients ---
    op.create_table(
        'recipe_ingredients',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'recipe_id',
            sa.Uuid(),
            sa.ForeignKey('recipes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'template_id',
            sa.Uuid(),
            sa.ForeignKey('product_templates.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('ingredient_group_name', sa.String(100), nullable=True),
        sa.Column('quantity', sa.Numeric(10, 3), nullable=False),
        sa.Column(
            'uom_id',
            sa.Uuid(),
            sa.ForeignKey('uoms.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('is_optional', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_recipe_ingredients_recipe_id', 'recipe_ingredients', ['recipe_id'])
    op.create_index('ix_recipe_ingredients_template_id', 'recipe_ingredients', ['template_id'])
    op.create_index('ix_recipe_ingredients_group_name', 'recipe_ingredients', ['ingredient_group_name'])

    # --- picking_sessions ---
    op.create_table(
        'picking_sessions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.Uuid(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'recipe_id',
            sa.Uuid(),
            sa.ForeignKey('recipes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('servings', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_picking_sessions_organization_id_status', 'picking_sessions', ['organization_id', 'status'])
    op.create_index('ix_picking_sessions_user_id_status', 'picking_sessions', ['user_id', 'status'])

    # --- picking_session_items ---
    op.create_table(
        'picking_session_items',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'session_id',
            sa.Uuid(),
            sa.ForeignKey('picking_sessions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'ingredient_id',
            sa.Uuid(),
            sa.ForeignKey('recipe_ingredients.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            sa.Uuid(),
            sa.ForeignKey('items.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('quantity_consumed', sa.Numeric(10, 3), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
    )
    op.create_index('ix_picking_session_items_session_id', 'picking_session_items', ['session_id'])


def downgrade() -> None:
    op.drop_table('picking_session_items')
    op.drop_table('picking_sessions')
    op.drop_table('recipe_ingredients')
    op.drop_table('recipes')
