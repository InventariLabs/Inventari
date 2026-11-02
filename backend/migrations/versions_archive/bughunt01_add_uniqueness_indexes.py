"""add partial unique indexes for barcode/sku/uom-reference

Revision ID: bughunt01
Revises: s6_6_strategy01
Create Date: 2026-06-27

Adds partial UNIQUE indexes that enforce uniqueness only over the meaningful
rows (excluding soft-deleted and NULL), closing several TOCTOU/duplicate
gaps found in a review of the core:

- items.barcode, product_templates.barcode, product_templates.sku had only
  non-unique indexes, so concurrent scans/inserts could create duplicates.
- Two UoMs in the same category could both be is_reference (ambiguous
  conversion target).

The indexes are PARTIAL (postgresql_where) so NULLs and soft-deleted rows are
excluded — matching the existing ix_items_org_barcode_active pattern.

IDEMPOTENCY: drops use if_exists=True to handle:
- DBs bootstrapped via SQLAlchemy create_all() (no auto-named indexes).
- The archived cf30d6efa74e migration which already created a partial unique
  on (organization_id, sku) under the name ix_product_templates_org_sku; we
  drop that too to avoid leaving a duplicate-index with identical definition.

NOTE: before applying in production, dedupe existing data:
  SELECT organization_id, barcode, count(*) FROM items
  WHERE barcode IS NOT NULL AND is_deleted = false
  GROUP BY organization_id, barcode HAVING count(*) > 1;
  (and the equivalent for product_templates.barcode/sku and uoms.is_reference)
If duplicates exist, resolve them first or the migration will fail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'bughunt01'
down_revision: str | None = 's6_6_strategy01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old non-unique indexes that would otherwise shadow / conflict
    # with the new unique ones. if_exists=True so this is safe on DBs where
    # the baseline never created these auto-named indexes.
    op.drop_index('ix_items_barcode', table_name='items', if_exists=True)
    op.drop_index(
        'ix_product_templates_barcode', table_name='product_templates', if_exists=True
    )
    op.drop_index(
        'ix_product_templates_sku', table_name='product_templates', if_exists=True
    )

    # Drop the equivalent partial unique index that the archived migration
    # cf30d6efa74e_add_sku_to_product_templates left behind under a different
    # name. Without this we'd end up with two identical indexes.
    op.drop_index(
        'ix_product_templates_org_sku', table_name='product_templates', if_exists=True
    )
    op.drop_index('ix_items_org_barcode_active', table_name='items', if_exists=True)

    # items.barcode: unique per org, excluding soft-deleted and NULL.
    op.create_index(
        'uq_items_org_barcode_active',
        'items',
        ['organization_id', 'barcode'],
        unique=True,
        postgresql_where=sa.text('barcode IS NOT NULL AND is_deleted = false'),
    )
    # product_templates.barcode: unique per org, excluding NULL.
    op.create_index(
        'uq_templates_org_barcode',
        'product_templates',
        ['organization_id', 'barcode'],
        unique=True,
        postgresql_where=sa.text('barcode IS NOT NULL'),
    )
    # product_templates.sku: unique per org, excluding NULL.
    op.create_index(
        'uq_templates_org_sku',
        'product_templates',
        ['organization_id', 'sku'],
        unique=True,
        postgresql_where=sa.text('sku IS NOT NULL'),
    )
    # At most one is_reference UoM per category.
    op.create_index(
        'uq_uom_category_reference',
        'uoms',
        ['category_id'],
        unique=True,
        postgresql_where=sa.text('is_reference = true'),
    )


def downgrade() -> None:
    op.drop_index('uq_uom_category_reference', table_name='uoms')
    op.drop_index('uq_templates_org_sku', table_name='product_templates')
    op.drop_index('uq_templates_org_barcode', table_name='product_templates')
    op.drop_index('uq_items_org_barcode_active', table_name='items')

    # Restore the original non-unique indexes (baseline_001 definitions).
    op.create_index('ix_items_barcode', 'items', ['barcode'])
    op.create_index('ix_product_templates_barcode', 'product_templates', ['barcode'])
    op.create_index('ix_product_templates_sku', 'product_templates', ['sku'])
    # Note: downgrade does NOT recreate ix_product_templates_org_sku because
    # that index was originally created by the now-archived cf30d6efa74e
    # migration. Restoring it here would split historical ownership; it can
    # be recreated manually if needed.
