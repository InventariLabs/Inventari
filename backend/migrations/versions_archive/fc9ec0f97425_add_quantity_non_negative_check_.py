"""add_quantity_non_negative_check_constraints

Revision ID: fc9ec0f97425
Revises: 16ed2c65cc4e
Create Date: 2026-05-29 08:39:56.743609

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'fc9ec0f97425'
down_revision: str | None = '16ed2c65cc4e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE items ADD CONSTRAINT ck_items_quantity_non_negative '
        "CHECK (quantity >= 0) NOT VALID"
    )
    op.execute(
        'ALTER TABLE stock_quants ADD CONSTRAINT ck_stock_quants_quantity_non_negative '
        "CHECK (quantity >= 0) NOT VALID"
    )
    op.execute(
        'ALTER TABLE stock_quants ADD CONSTRAINT ck_stock_quants_reserved_non_negative '
        "CHECK (reserved_quantity >= 0) NOT VALID"
    )
    op.execute(
        'ALTER TABLE stock_quants ADD CONSTRAINT ck_stock_quants_reserved_le_quantity '
        "CHECK (reserved_quantity <= quantity) NOT VALID"
    )

    op.execute('ALTER TABLE items VALIDATE CONSTRAINT ck_items_quantity_non_negative')
    op.execute(
        'ALTER TABLE stock_quants VALIDATE CONSTRAINT ck_stock_quants_quantity_non_negative'
    )
    op.execute(
        'ALTER TABLE stock_quants VALIDATE CONSTRAINT ck_stock_quants_reserved_non_negative'
    )
    op.execute(
        'ALTER TABLE stock_quants VALIDATE CONSTRAINT ck_stock_quants_reserved_le_quantity'
    )

    op.execute(
        'ALTER TABLE stock_quants DROP CONSTRAINT uq_quant_product_location_lot_package'
    )
    op.execute(
        'ALTER TABLE stock_quants ADD CONSTRAINT uq_quant_product_location_lot_package '
        'UNIQUE (organization_id, product_template_id, storage_location_id, lot_id, package_id)'
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE stock_quants DROP CONSTRAINT uq_quant_product_location_lot_package'
    )
    op.execute(
        'ALTER TABLE stock_quants ADD CONSTRAINT uq_quant_product_location_lot_package '
        'UNIQUE (organization_id, product_template_id, storage_location_id, lot_id, package_id)'
    )
    op.execute('ALTER TABLE stock_quants DROP CONSTRAINT ck_stock_quants_reserved_le_quantity')
    op.execute('ALTER TABLE stock_quants DROP CONSTRAINT ck_stock_quants_reserved_non_negative')
    op.execute('ALTER TABLE stock_quants DROP CONSTRAINT ck_stock_quants_quantity_non_negative')
    op.execute('ALTER TABLE items DROP CONSTRAINT ck_items_quantity_non_negative')
