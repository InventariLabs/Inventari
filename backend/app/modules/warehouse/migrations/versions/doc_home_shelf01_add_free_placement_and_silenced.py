"""add the free-storage setting and the products not asked about a home shelf.

Revision ID: doc_home_shelf01
Revises: doc_count_expectation01
Create Date: 2026-10-25

``document_warehouse_receiving.free_placement`` (default False) marks a warehouse
that stores goods wherever there is room; its put-away never asks whether the
shelf used is a product's home. ``putaway_home_silenced`` holds one row per
product the question is no longer asked about.

Downgrade drops both.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_home_shelf01'
down_revision: str | None = 'doc_count_expectation01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_warehouse_receiving',
        sa.Column(
            'free_placement',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        'putaway_home_silenced',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.Uuid(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            sa.Uuid(),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_putaway_home_silenced_org_product',
        ),
    )
    op.create_index(
        'ix_putaway_home_silenced_organization_id',
        'putaway_home_silenced',
        ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_putaway_home_silenced_organization_id',
        table_name='putaway_home_silenced',
    )
    op.drop_table('putaway_home_silenced')
    op.drop_column('document_warehouse_receiving', 'free_placement')
