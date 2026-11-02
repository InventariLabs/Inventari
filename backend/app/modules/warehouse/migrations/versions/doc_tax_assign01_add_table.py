"""add the products and categories that name their tax rate.

Revision ID: doc_tax_assign01
Revises: doc_list_reads01
Create Date: 2026-10-27

``tax_rate_assignments`` holds one row per product, or per category, that
names one of the organization's ``tax_rates``: a new document line for that
product takes the rate before the profile's or the country's default. A row
names exactly one of the two targets.

Downgrade drops the table; the lines already written keep their rates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_tax_assign01'
down_revision: str | None = 'doc_list_reads01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'tax_rate_assignments',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.Uuid(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'tax_rate_id',
            sa.Uuid(),
            sa.ForeignKey('tax_rates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            sa.Uuid(),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column(
            'category_id',
            sa.Uuid(),
            sa.ForeignKey('categories.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.CheckConstraint(
            'num_nonnulls(product_template_id, category_id) = 1',
            name='ck_tax_rate_assignments_one_target',
        ),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_tax_rate_assignments_org_product',
        ),
        sa.UniqueConstraint(
            'organization_id',
            'category_id',
            name='uq_tax_rate_assignments_org_category',
        ),
    )
    op.create_index(
        'ix_tax_rate_assignments_organization_id',
        'tax_rate_assignments',
        ['organization_id'],
    )
    op.create_index(
        'ix_tax_rate_assignments_tax_rate_id',
        'tax_rate_assignments',
        ['tax_rate_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_tax_rate_assignments_tax_rate_id', table_name='tax_rate_assignments'
    )
    op.drop_index(
        'ix_tax_rate_assignments_organization_id', table_name='tax_rate_assignments'
    )
    op.drop_table('tax_rate_assignments')
