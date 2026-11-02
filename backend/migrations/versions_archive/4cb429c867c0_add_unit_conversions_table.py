"""add unit_conversions table

Revision ID: 4cb429c867c0
Revises: 3d49c70da606
Create Date: 2026-04-06 17:14:34.079855

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cb429c867c0'
down_revision: Union[str, None] = '3d49c70da606'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('unit_conversions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('ingredient_key', sa.String(length=100), nullable=False),
    sa.Column('ingredient_name', sa.String(length=200), nullable=False),
    sa.Column('source_unit', sa.String(length=50), nullable=False),
    sa.Column('metric_quantity', sa.Numeric(precision=10, scale=3), nullable=False),
    sa.Column('metric_unit', sa.String(length=10), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'ingredient_key', 'source_unit', name='uq_unit_conv_org_ingredient_unit')
    )
    op.create_index('ix_unit_conv_lookup', 'unit_conversions', ['ingredient_key', 'source_unit', 'organization_id'], unique=False)
    op.create_index(op.f('ix_unit_conversions_ingredient_key'), 'unit_conversions', ['ingredient_key'], unique=False)
    op.create_index(op.f('ix_unit_conversions_organization_id'), 'unit_conversions', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_unit_conversions_organization_id'), table_name='unit_conversions')
    op.drop_index(op.f('ix_unit_conversions_ingredient_key'), table_name='unit_conversions')
    op.drop_index('ix_unit_conv_lookup', table_name='unit_conversions')
    op.drop_table('unit_conversions')
