"""add ingredient price and template default price

Revision ID: 0a010f3ac3fb
Revises: 229bfe19c98b
Create Date: 2026-05-10 20:41:34.123921

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0a010f3ac3fb'
down_revision: Union[str, None] = '229bfe19c98b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('product_templates', sa.Column('default_price', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('product_templates', sa.Column('default_price_uom_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_product_templates_default_price_uom', 'product_templates', 'uoms', ['default_price_uom_id'], ['id'])

    op.add_column('recipe_ingredients', sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('recipe_ingredients', sa.Column('price_uom_id', sa.Uuid(), nullable=True))
    op.add_column('recipe_ingredients', sa.Column('price_currency', sa.String(length=3), nullable=True))
    op.create_foreign_key('fk_recipe_ingredients_price_uom', 'recipe_ingredients', 'uoms', ['price_uom_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_recipe_ingredients_price_uom', 'recipe_ingredients', type_='foreignkey')
    op.drop_column('recipe_ingredients', 'price_currency')
    op.drop_column('recipe_ingredients', 'price_uom_id')
    op.drop_column('recipe_ingredients', 'price')

    op.drop_constraint('fk_product_templates_default_price_uom', 'product_templates', type_='foreignkey')
    op.drop_column('product_templates', 'default_price_uom_id')
    op.drop_column('product_templates', 'default_price')
