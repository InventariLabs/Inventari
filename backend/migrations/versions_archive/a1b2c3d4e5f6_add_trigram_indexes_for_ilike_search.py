"""add trigram indexes for ILIKE search

Revision ID: a1b2c3d4e5f6
Revises: f69cdbf5fa50
Create Date: 2026-04-21 15:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f69cdbf5fa50'
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table, "col": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_items_name_trgm '
        'ON items USING gin (name gin_trgm_ops)'
    )
    if _col_exists('items', 'barcode'):
        op.execute(
            'CREATE INDEX IF NOT EXISTS ix_items_barcode_trgm '
            'ON items USING gin (barcode gin_trgm_ops)'
        )
    if _col_exists('items', 'brand'):
        op.execute(
            'CREATE INDEX IF NOT EXISTS ix_items_brand_trgm '
            'ON items USING gin (brand gin_trgm_ops)'
        )
    if _col_exists('items', 'label_code'):
        op.execute(
            'CREATE INDEX IF NOT EXISTS ix_items_label_code_trgm '
            'ON items USING gin (label_code gin_trgm_ops)'
        )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_product_templates_name_trgm '
        'ON product_templates USING gin (name gin_trgm_ops)'
    )
    if _col_exists('product_templates', 'sku'):
        op.execute(
            'CREATE INDEX IF NOT EXISTS ix_product_templates_sku_trgm '
            'ON product_templates USING gin (sku gin_trgm_ops)'
        )
    if _col_exists('partners', 'name'):
        op.execute(
            'CREATE INDEX IF NOT EXISTS ix_partners_name_trgm '
            'ON partners USING gin (name gin_trgm_ops)'
        )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_partners_name_trgm')
    op.execute('DROP INDEX IF EXISTS ix_product_templates_sku_trgm')
    op.execute('DROP INDEX IF EXISTS ix_product_templates_name_trgm')
    op.execute('DROP INDEX IF EXISTS ix_items_label_code_trgm')
    op.execute('DROP INDEX IF EXISTS ix_items_brand_trgm')
    op.execute('DROP INDEX IF EXISTS ix_items_barcode_trgm')
    op.execute('DROP INDEX IF EXISTS ix_items_name_trgm')
