"""add organization_id to uoms and uom_categories

Revision ID: b2a1c3d4e5f6
Revises: 89017ff13f55
Create Date: 2026-04-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'b2a1c3d4e5f6'
down_revision: Union[str, None] = '89017ff13f55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'uom_categories',
        sa.Column('organization_id', UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_uom_categories_organization_id',
        'uom_categories',
        'organizations',
        ['organization_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_index(
        'ix_uom_categories_organization_id',
        'uom_categories',
        ['organization_id'],
    )

    op.add_column(
        'uoms',
        sa.Column('organization_id', UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'uoms',
        sa.Column('is_system', sa.Boolean(), nullable=True, server_default=sa.text('false')),
    )
    op.create_foreign_key(
        'fk_uoms_organization_id',
        'uoms',
        'organizations',
        ['organization_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_index(
        'ix_uoms_organization_id',
        'uoms',
        ['organization_id'],
    )

    op.drop_constraint('uom_categories_name_key', 'uom_categories', type_='unique')
    op.create_unique_constraint(
        'uq_uom_category_org_name',
        'uom_categories',
        ['organization_id', 'name'],
    )

    op.drop_constraint('uoms_name_key', 'uoms', type_='unique')
    op.create_unique_constraint(
        'uq_uom_org_name',
        'uoms',
        ['organization_id', 'name'],
    )

    op.execute(
        "UPDATE uoms SET is_system = true WHERE organization_id IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint('uq_uom_org_name', 'uoms', type_='unique')
    op.create_unique_constraint('uoms_name_key', 'uoms', ['name'])

    op.drop_constraint('uq_uom_category_org_name', 'uom_categories', type_='unique')
    op.create_unique_constraint('uom_categories_name_key', 'uom_categories', ['name'])

    op.drop_index('ix_uoms_organization_id', table_name='uoms')
    op.drop_constraint('fk_uoms_organization_id', 'uoms', type_='foreignkey')
    op.drop_column('uoms', 'is_system')
    op.drop_column('uoms', 'organization_id')

    op.drop_index('ix_uom_categories_organization_id', table_name='uom_categories')
    op.drop_constraint(
        'fk_uom_categories_organization_id', 'uom_categories', type_='foreignkey'
    )
    op.drop_column('uom_categories', 'organization_id')
