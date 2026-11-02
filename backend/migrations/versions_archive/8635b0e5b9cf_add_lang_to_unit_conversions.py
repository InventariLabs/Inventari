"""add_lang_to_unit_conversions

Revision ID: 8635b0e5b9cf
Revises: 4cb429c867c0
Create Date: 2026-04-06 18:57:47.752657

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8635b0e5b9cf'
down_revision: Union[str, None] = '4cb429c867c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add lang column with server_default so existing rows get 'en'
    op.add_column(
        'unit_conversions',
        sa.Column('lang', sa.String(length=5), nullable=False, server_default='en'),
    )
    # Drop old constraint, rebuild with lang
    op.drop_constraint('uq_unit_conv_org_ingredient_unit', 'unit_conversions', type_='unique')
    op.drop_index('ix_unit_conv_lookup', table_name='unit_conversions')
    op.create_index(
        'ix_unit_conv_lookup',
        'unit_conversions',
        ['ingredient_key', 'source_unit', 'lang', 'organization_id'],
        unique=False,
    )
    op.create_unique_constraint(
        'uq_unit_conv_org_ingredient_unit_lang',
        'unit_conversions',
        ['organization_id', 'ingredient_key', 'source_unit', 'lang'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_unit_conv_org_ingredient_unit_lang', 'unit_conversions', type_='unique')
    op.drop_index('ix_unit_conv_lookup', table_name='unit_conversions')
    op.create_index(
        'ix_unit_conv_lookup',
        'unit_conversions',
        ['ingredient_key', 'source_unit', 'organization_id'],
        unique=False,
    )
    op.create_unique_constraint(
        'uq_unit_conv_org_ingredient_unit',
        'unit_conversions',
        ['organization_id', 'ingredient_key', 'source_unit'],
    )
    op.drop_column('unit_conversions', 'lang')
