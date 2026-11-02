"""add recipe_tag_configs table

Revision ID: 9b62c30a2fbd
Revises: d6cf8f0ea2ea
Create Date: 2026-03-18 22:44:17.362019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9b62c30a2fbd'
down_revision: Union[str, None] = 'd6cf8f0ea2ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recipe_tag_configs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_recipe_tag_configs_org_name'),
    )
    op.create_index(
        op.f('ix_recipe_tag_configs_organization_id'),
        'recipe_tag_configs',
        ['organization_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_recipe_tag_configs_organization_id'),
        table_name='recipe_tag_configs',
    )
    op.drop_table('recipe_tag_configs')
