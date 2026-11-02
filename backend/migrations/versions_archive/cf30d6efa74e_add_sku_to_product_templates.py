"""add_sku_to_product_templates

Revision ID: cf30d6efa74e
Revises: ae7c063d63f7
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cf30d6efa74e'
down_revision: Union[str, None] = 'ae7c063d63f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('product_templates', sa.Column('sku', sa.String(50), nullable=True))
    op.create_index(
        'ix_product_templates_org_sku',
        'product_templates',
        ['organization_id', 'sku'],
        unique=True,
        postgresql_where=sa.text('sku IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_product_templates_org_sku')
    op.drop_column('product_templates', 'sku')
