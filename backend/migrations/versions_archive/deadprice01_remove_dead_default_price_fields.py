"""remove dead default_price fields from product_templates

Revision ID: deadprice01
Revises: 6b1add11450c
Create Date: 2026-06-15 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'deadprice01'
down_revision: Union[str, None] = '6b1add11450c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE product_templates '
        'DROP CONSTRAINT IF EXISTS fk_product_templates_default_price_uom'
    )
    op.drop_column('product_templates', 'default_price_uom_id')
    op.drop_column('product_templates', 'default_price')


def downgrade() -> None:
    op.add_column('product_templates', sa.Column('default_price', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('product_templates', sa.Column('default_price_uom_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_product_templates_default_price_uom', 'product_templates', 'uoms', ['default_price_uom_id'], ['id'])
