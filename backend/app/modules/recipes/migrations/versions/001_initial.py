"""recipes module baseline — create 10 recipe-related tables.

Initial migration for the recipes module, extracted from core baseline_001
as part of the module migration isolation effort.

Tables (creation order respects FK dependencies):
- recipe_tag_configs (FK -> organizations)
- recipes (FK -> organizations, users)
- recipe_ingredients (FK -> recipes, product_templates, uoms x2)
- picking_sessions (FK -> organizations, recipes, users)
- picking_session_items (FK -> picking_sessions, recipe_ingredients, items)
- ingredient_nutrition_defaults (FK -> organizations, nullable)
- unit_conversions (FK -> organizations, nullable)
- meal_plans (FK -> organizations, users)
- meal_plan_entries (FK -> meal_plans, recipes; uses mealslot enum)
- shopping_exclusions (FK -> organizations, product_templates)

Two core incremental migrations were guarded for fresh installs:
- ``pickitems01`` (add picked_items JSONB to picking_session_items):
  no-op when the table does not exist (module owns it now).
- ``avcosnap01`` (add consumed_valuation_rate to picking_session_items):
  no-op when the table does not exist (module owns it now).

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('recipes',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- recipe_tag_configs ---
    create_table_if_absent(
        'recipe_tag_configs',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id', 'name', name='uq_recipe_tag_configs_org_name'
        ),
    )
    create_index_if_absent(
        'ix_recipe_tag_configs_organization_id',
        'recipe_tag_configs',
        ['organization_id'],
    )

    # --- recipes ---
    create_table_if_absent(
        'recipes',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('servings', sa.Integer(), nullable=False),
        sa.Column('prep_time_minutes', sa.Integer(), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('tags', postgresql.JSONB(), nullable=True),
        sa.Column('is_favorite', sa.Boolean(), nullable=False),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent('ix_recipes_organization_id', 'recipes', ['organization_id'])
    create_index_if_absent('ix_recipes_is_favorite', 'recipes', ['is_favorite'])

    # --- recipe_ingredients ---
    create_table_if_absent(
        'recipe_ingredients',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'recipe_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('recipes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('display_text', sa.String(500), nullable=True),
        sa.Column('ingredient_group_name', sa.String(100), nullable=True),
        sa.Column('quantity', sa.Numeric(10, 3), nullable=False),
        sa.Column(
            'uom_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('original_quantity', sa.Numeric(10, 3), nullable=True),
        sa.Column('original_unit_text', sa.String(50), nullable=True),
        sa.Column('is_optional', sa.Boolean(), nullable=False),
        sa.Column('picking_skip', sa.Boolean(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('calories_kcal_per_100g', sa.Numeric(8, 2), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=True),
        sa.Column(
            'price_uom_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('price_currency', sa.String(3), nullable=True),
    )
    create_index_if_absent(
        'ix_recipe_ingredients_template_id', 'recipe_ingredients', ['template_id']
    )
    create_index_if_absent(
        'ix_recipe_ingredients_ingredient_group_name',
        'recipe_ingredients',
        ['ingredient_group_name'],
    )
    create_index_if_absent(
        'ix_recipe_ingredients_recipe_id', 'recipe_ingredients', ['recipe_id']
    )

    # --- picking_sessions ---
    create_table_if_absent(
        'picking_sessions',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'recipe_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('recipes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column('servings', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
    )
    create_index_if_absent('ix_picking_sessions_user_id', 'picking_sessions', ['user_id'])
    create_index_if_absent(
        'ix_picking_sessions_organization_id', 'picking_sessions', ['organization_id']
    )

    # --- picking_session_items (FINAL state includes picked_items + consumed_valuation_rate) ---
    create_table_if_absent(
        'picking_session_items',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('picking_sessions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'ingredient_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('recipe_ingredients.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('quantity_consumed', sa.Numeric(10, 3), nullable=True),
        sa.Column('picked_items', postgresql.JSONB(), nullable=True),
        sa.Column('consumed_valuation_rate', sa.Numeric(12, 2), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
    )
    create_index_if_absent(
        'ix_picking_session_items_session_id',
        'picking_session_items',
        ['session_id'],
    )

    # --- ingredient_nutrition_defaults ---
    create_table_if_absent(
        'ingredient_nutrition_defaults',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('lang', sa.String(5), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('name_normalized', sa.String(255), nullable=False),
        sa.Column('calories_kcal', sa.Numeric(8, 2), nullable=False),
        sa.Column('protein_g', sa.Numeric(8, 2), nullable=True),
        sa.Column('fat_g', sa.Numeric(8, 2), nullable=True),
        sa.Column('carbs_g', sa.Numeric(8, 2), nullable=True),
        sa.Column('fiber_g', sa.Numeric(8, 2), nullable=True),
        sa.Column('sugar_g', sa.Numeric(8, 2), nullable=True),
        sa.Column('salt_g', sa.Numeric(8, 2), nullable=True),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'lang',
            'name_normalized',
            name='uq_ingredient_defaults_org_lang_name',
        ),
    )
    create_index_if_absent(
        'ix_ingredient_nutrition_defaults_organization_id',
        'ingredient_nutrition_defaults',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_ingredient_nutrition_defaults_name_normalized',
        'ingredient_nutrition_defaults',
        ['name_normalized'],
    )
    create_index_if_absent(
        'ix_ingredient_defaults_lookup',
        'ingredient_nutrition_defaults',
        ['name_normalized', 'lang', 'organization_id'],
    )

    # --- unit_conversions ---
    create_table_if_absent(
        'unit_conversions',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('lang', sa.String(5), nullable=False),
        sa.Column('ingredient_key', sa.String(100), nullable=False),
        sa.Column('ingredient_name', sa.String(200), nullable=False),
        sa.Column('source_unit', sa.String(50), nullable=False),
        sa.Column('metric_quantity', sa.Numeric(10, 3), nullable=False),
        sa.Column('metric_unit', sa.String(10), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            'organization_id',
            'ingredient_key',
            'source_unit',
            'lang',
            name='uq_unit_conv_org_ingredient_unit_lang',
        ),
    )
    create_index_if_absent(
        'ix_unit_conv_lookup',
        'unit_conversions',
        ['ingredient_key', 'source_unit', 'lang', 'organization_id'],
    )
    create_index_if_absent(
        'ix_unit_conversions_organization_id', 'unit_conversions', ['organization_id']
    )
    create_index_if_absent(
        'ix_unit_conversions_ingredient_key', 'unit_conversions', ['ingredient_key']
    )

    # --- meal_plans ---
    create_table_if_absent(
        'meal_plans',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('enabled_slots', postgresql.JSONB(), nullable=False),
        sa.Column('default_servings', sa.Integer(), nullable=True),
        sa.Column('shopping_list_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_meal_plans_org_start', 'meal_plans', ['organization_id', 'start_date']
    )
    create_index_if_absent(
        'ix_meal_plans_org_end', 'meal_plans', ['organization_id', 'end_date']
    )
    create_index_if_absent('ix_meal_plans_organization_id', 'meal_plans', ['organization_id'])

    # --- mealslot enum (required by meal_plan_entries) ---
    mealslot_enum = postgresql.ENUM(
        'LUNCH', 'BREAKFAST', 'DINNER', 'SNACK', name='mealslot', create_type=False
    )
    mealslot_enum.create(op.get_bind(), checkfirst=True)

    # --- meal_plan_entries ---
    create_table_if_absent(
        'meal_plan_entries',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'meal_plan_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('meal_plans.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column(
            'slot',
            postgresql.ENUM(
                'LUNCH',
                'BREAKFAST',
                'DINNER',
                'SNACK',
                name='mealslot',
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            'recipe_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('recipes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('servings', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            'meal_plan_id',
            'date',
            'slot',
            'order',
            name='uq_meal_plan_entries_plan_date_slot_order',
        ),
    )
    create_index_if_absent(
        'ix_meal_plan_entries_plan_date',
        'meal_plan_entries',
        ['meal_plan_id', 'date'],
    )
    create_index_if_absent(
        'ix_meal_plan_entries_meal_plan_id', 'meal_plan_entries', ['meal_plan_id']
    )
    create_index_if_absent('ix_meal_plan_entries_recipe', 'meal_plan_entries', ['recipe_id'])
    create_index_if_absent('ix_meal_plan_entries_date', 'meal_plan_entries', ['date'])

    # --- shopping_exclusions ---
    create_table_if_absent(
        'shopping_exclusions',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('name_normalized', sa.String(255), nullable=False),
        sa.Column(
            'template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'name_normalized',
            name='uq_shopping_exclusions_org_name',
        ),
    )
    create_index_if_absent(
        'ix_shopping_exclusions_organization_id',
        'shopping_exclusions',
        ['organization_id'],
    )


def downgrade() -> None:
    # Drop children first (FK reverse order)
    op.drop_index(
        'ix_shopping_exclusions_organization_id', table_name='shopping_exclusions'
    )
    op.drop_table('shopping_exclusions')

    op.drop_index('ix_meal_plan_entries_date', table_name='meal_plan_entries')
    op.drop_index('ix_meal_plan_entries_recipe', table_name='meal_plan_entries')
    op.drop_index('ix_meal_plan_entries_meal_plan_id', table_name='meal_plan_entries')
    op.drop_index('ix_meal_plan_entries_plan_date', table_name='meal_plan_entries')
    op.drop_table('meal_plan_entries')
    postgresql.ENUM(name='mealslot').drop(op.get_bind(), checkfirst=True)

    op.drop_index('ix_meal_plans_organization_id', table_name='meal_plans')
    op.drop_index('ix_meal_plans_org_end', table_name='meal_plans')
    op.drop_index('ix_meal_plans_org_start', table_name='meal_plans')
    op.drop_table('meal_plans')

    op.drop_index('ix_unit_conversions_ingredient_key', table_name='unit_conversions')
    op.drop_index('ix_unit_conversions_organization_id', table_name='unit_conversions')
    op.drop_index('ix_unit_conv_lookup', table_name='unit_conversions')
    op.drop_table('unit_conversions')

    op.drop_index(
        'ix_ingredient_defaults_lookup', table_name='ingredient_nutrition_defaults'
    )
    op.drop_index(
        'ix_ingredient_nutrition_defaults_name_normalized',
        table_name='ingredient_nutrition_defaults',
    )
    op.drop_index(
        'ix_ingredient_nutrition_defaults_organization_id',
        table_name='ingredient_nutrition_defaults',
    )
    op.drop_table('ingredient_nutrition_defaults')

    op.drop_index(
        'ix_picking_session_items_session_id', table_name='picking_session_items'
    )
    op.drop_table('picking_session_items')

    op.drop_index('ix_picking_sessions_organization_id', table_name='picking_sessions')
    op.drop_index('ix_picking_sessions_user_id', table_name='picking_sessions')
    op.drop_table('picking_sessions')

    op.drop_index('ix_recipe_ingredients_recipe_id', table_name='recipe_ingredients')
    op.drop_index(
        'ix_recipe_ingredients_ingredient_group_name',
        table_name='recipe_ingredients',
    )
    op.drop_index('ix_recipe_ingredients_template_id', table_name='recipe_ingredients')
    op.drop_table('recipe_ingredients')

    op.drop_index('ix_recipes_is_favorite', table_name='recipes')
    op.drop_index('ix_recipes_organization_id', table_name='recipes')
    op.drop_table('recipes')

    op.drop_index(
        'ix_recipe_tag_configs_organization_id', table_name='recipe_tag_configs'
    )
    op.drop_table('recipe_tag_configs')
