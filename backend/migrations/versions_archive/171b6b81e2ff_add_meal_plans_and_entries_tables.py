"""add_meal_plans_and_entries_tables

Revision ID: 171b6b81e2ff
Revises: a95122e492a6
Create Date: 2026-05-10 11:54:02.816576

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '171b6b81e2ff'
down_revision: Union[str, None] = 'a95122e492a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'meal_plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column(
            'enabled_slots',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column('default_servings', sa.Integer(), nullable=True),
        sa.Column('shopping_list_id', sa.Uuid(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['shopping_list_id'], ['shopping_lists.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_meal_plans_org_end', 'meal_plans', ['organization_id', 'end_date'], unique=False
    )
    op.create_index(
        'ix_meal_plans_org_start', 'meal_plans', ['organization_id', 'start_date'], unique=False
    )
    op.create_index(
        op.f('ix_meal_plans_organization_id'), 'meal_plans', ['organization_id'], unique=False
    )

    op.create_table(
        'meal_plan_entries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('meal_plan_id', sa.Uuid(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column(
            'slot',
            sa.Enum('LUNCH', 'BREAKFAST', 'DINNER', 'SNACK', name='mealslot'),
            nullable=False,
        ),
        sa.Column('recipe_id', sa.Uuid(), nullable=False),
        sa.Column('servings', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['meal_plan_id'], ['meal_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'meal_plan_id', 'date', 'slot', 'order',
            name='uq_meal_plan_entries_plan_date_slot_order',
        ),
    )
    op.create_index(
        'ix_meal_plan_entries_date', 'meal_plan_entries', ['date'], unique=False
    )
    op.create_index(
        op.f('ix_meal_plan_entries_meal_plan_id'),
        'meal_plan_entries',
        ['meal_plan_id'],
        unique=False,
    )
    op.create_index(
        'ix_meal_plan_entries_plan_date',
        'meal_plan_entries',
        ['meal_plan_id', 'date'],
        unique=False,
    )
    op.create_index(
        'ix_meal_plan_entries_recipe', 'meal_plan_entries', ['recipe_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_meal_plan_entries_recipe', table_name='meal_plan_entries')
    op.drop_index('ix_meal_plan_entries_plan_date', table_name='meal_plan_entries')
    op.drop_index(
        op.f('ix_meal_plan_entries_meal_plan_id'), table_name='meal_plan_entries'
    )
    op.drop_index('ix_meal_plan_entries_date', table_name='meal_plan_entries')
    op.drop_table('meal_plan_entries')
    op.drop_index(op.f('ix_meal_plans_organization_id'), table_name='meal_plans')
    op.drop_index('ix_meal_plans_org_start', table_name='meal_plans')
    op.drop_index('ix_meal_plans_org_end', table_name='meal_plans')
    op.drop_table('meal_plans')
    sa.Enum(name='mealslot').drop(op.get_bind(), checkfirst=True)
