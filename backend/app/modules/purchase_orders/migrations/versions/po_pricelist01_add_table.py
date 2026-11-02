"""add po_partner_pricelist table

Revision ID: po_pricelist01
Revises: po_reorder_rules01
Create Date: 2026-06-25

Per-supplier price list entries. Each row says: "supplier P charges
``unit_price`` per ``uom_id`` for product T, with tier ``min_quantity``
threshold, valid between ``valid_from`` and ``valid_to``."

Used by:
- Recipes cost estimate: fallback in the cost-estimate chain (AVCO →
  supplier price → static purchase_price → 0)
- Auto-PO generation: pick preferred_partner with lowest current price
- Procurement UI: compare supplier offers for the same product
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'po_pricelist01'
down_revision: str | None = 'po_reorder_rules01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'po_partner_pricelist',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'partner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('unit_price', sa.Numeric(12, 4), nullable=False),
        sa.Column(
            'currency',
            sa.String(3),
            nullable=False,
            server_default='USD',
        ),
        sa.Column(
            'uom_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'min_quantity',
            sa.Numeric(12, 3),
            nullable=True,
        ),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            'unit_price > 0',
            name='ck_po_partner_pricelist_unit_price_positive',
        ),
        sa.CheckConstraint(
            'valid_to IS NULL OR valid_to >= valid_from',
            name='ck_po_partner_pricelist_valid_range',
        ),
        sa.CheckConstraint(
            'min_quantity IS NULL OR min_quantity > 0',
            name='ck_po_partner_pricelist_min_qty_positive',
        ),
    )
    op.create_index(
        'ix_po_partner_pricelist_organization_id',
        'po_partner_pricelist',
        ['organization_id'],
    )
    op.create_index(
        'ix_po_partner_pricelist_partner_id',
        'po_partner_pricelist',
        ['partner_id'],
    )
    op.create_index(
        'ix_po_partner_pricelist_product_template_id',
        'po_partner_pricelist',
        ['product_template_id'],
    )
    # Composite index for the common "best price for template at date" query
    op.create_index(
        'ix_po_partner_pricelist_template_active',
        'po_partner_pricelist',
        ['product_template_id', 'valid_from', 'valid_to'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_po_partner_pricelist_template_active', table_name='po_partner_pricelist'
    )
    op.drop_index(
        'ix_po_partner_pricelist_product_template_id', table_name='po_partner_pricelist'
    )
    op.drop_index('ix_po_partner_pricelist_partner_id', table_name='po_partner_pricelist')
    op.drop_index(
        'ix_po_partner_pricelist_organization_id', table_name='po_partner_pricelist'
    )
    op.drop_table('po_partner_pricelist')