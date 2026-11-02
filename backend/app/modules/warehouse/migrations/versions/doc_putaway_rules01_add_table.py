"""add putaway_rules table

Revision ID: doc_putaway_rules01
Revises: 001_initial
Create Date: 2026-07-11

Per-organization putaway routing rules. The receipt executor consults
``resolve_putaway_location_async`` before falling back to the document's
``target_location_id`` — auto-routes fresh stock to the right zone
(FREEZER, FRIDGE, ...) or to a per-product / per-category bin.

Match keys are all optional but at least one must be set (CHECK).
Resolution specificity: product_template > category > context_tag >
storage_type_code. Within the same tier, ``priority`` (lower wins)
breaks ties.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'doc_putaway_rules01'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'putaway_rules',
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
            'product_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column(
            'category_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('categories.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('context_tag', sa.String(length=100), nullable=True),
        sa.Column('storage_type_code', sa.String(length=50), nullable=True),
        sa.Column(
            'target_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column(
            'is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            '(product_template_id IS NOT NULL) OR '
            '(category_id IS NOT NULL) OR '
            '(context_tag IS NOT NULL) OR '
            '(storage_type_code IS NOT NULL)',
            name='ck_putaway_rules_at_least_one_match',
        ),
    )
    op.create_index(
        'ix_putaway_rules_org_priority',
        'putaway_rules',
        ['organization_id', 'priority'],
    )
    op.create_index(
        'ix_putaway_rules_org_product',
        'putaway_rules',
        ['organization_id', 'product_template_id'],
    )
    op.create_index(
        'ix_putaway_rules_org_category',
        'putaway_rules',
        ['organization_id', 'category_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_putaway_rules_org_category', table_name='putaway_rules')
    op.drop_index('ix_putaway_rules_org_product', table_name='putaway_rules')
    op.drop_index('ix_putaway_rules_org_priority', table_name='putaway_rules')
    op.drop_table('putaway_rules')
