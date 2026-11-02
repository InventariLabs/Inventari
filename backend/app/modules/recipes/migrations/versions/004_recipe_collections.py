"""create recipe_collections and recipe_collection_members

Adds hierarchical folders for recipe libraries:
- recipe_collections (org-scoped, optional parent for nesting)
- recipe_collection_members (M2M to recipes)

Revision ID: 004_recipe_collections
Revises: 003_backfill_allergens
Create Date: 2026-08-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '004_recipe_collections'
down_revision: str | None = '003_backfill_allergens'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'recipe_collections',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.Uuid(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column(
            'parent_id',
            sa.Uuid(),
            sa.ForeignKey('recipe_collections.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column(
            'created_by',
            sa.Uuid(),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id', 'name', name='uq_recipe_collections_org_name'
        ),
    )
    op.create_index(
        'ix_recipe_collections_organization_id',
        'recipe_collections',
        ['organization_id'],
    )
    op.create_index(
        'ix_recipe_collections_parent_id',
        'recipe_collections',
        ['parent_id'],
    )

    op.create_table(
        'recipe_collection_members',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'collection_id',
            sa.Uuid(),
            sa.ForeignKey('recipe_collections.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'recipe_id',
            sa.Uuid(),
            sa.ForeignKey('recipes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'collection_id', 'recipe_id', name='uq_recipe_collection_members'
        ),
    )
    op.create_index(
        'ix_recipe_collection_members_collection_id',
        'recipe_collection_members',
        ['collection_id'],
    )
    op.create_index(
        'ix_recipe_collection_members_recipe_id',
        'recipe_collection_members',
        ['recipe_id'],
    )


def downgrade() -> None:
    op.drop_table('recipe_collection_members')
    op.drop_table('recipe_collections')
