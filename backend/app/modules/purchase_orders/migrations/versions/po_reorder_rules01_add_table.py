"""add po_reorder_rules table

Revision ID: po_reorder_rules01
Revises: 001_initial
Create Date: 2026-06-23

Per-location reorder thresholds for the ``purchase_orders`` module.
Each row says: "for product P at location L, trigger a reorder when
available stock drops below ``min_quantity``, target ``max_quantity``
on replenishment, and never go below ``safety_stock``."

Replaces the flat ``ProductTemplate.min_quantity`` field for
replenishment decisions (the template field remains for legacy
``replenishment_service`` callers).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'po_reorder_rules01'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'po_reorder_rules',
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
            'product_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'storage_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'min_quantity',
            sa.Numeric(12, 3),
            nullable=False,
            server_default='0',
        ),
        sa.Column('max_quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'safety_stock',
            sa.Numeric(12, 3),
            nullable=False,
            server_default='0',
        ),
        sa.Column(
            'preferred_partner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            'storage_location_id',
            name='uq_po_reorder_rules_org_product_loc',
        ),
        sa.CheckConstraint(
            'min_quantity >= 0',
            name='ck_po_reorder_rules_min_nonneg',
        ),
        sa.CheckConstraint(
            'max_quantity >= min_quantity',
            name='ck_po_reorder_rules_max_ge_min',
        ),
        sa.CheckConstraint(
            'safety_stock >= 0',
            name='ck_po_reorder_rules_safety_nonneg',
        ),
    )
    op.create_index(
        'ix_po_reorder_rules_organization_id',
        'po_reorder_rules',
        ['organization_id'],
    )
    op.create_index(
        'ix_po_reorder_rules_product_template_id',
        'po_reorder_rules',
        ['product_template_id'],
    )
    op.create_index(
        'ix_po_reorder_rules_storage_location_id',
        'po_reorder_rules',
        ['storage_location_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_po_reorder_rules_storage_location_id', table_name='po_reorder_rules'
    )
    op.drop_index(
        'ix_po_reorder_rules_product_template_id', table_name='po_reorder_rules'
    )
    op.drop_index('ix_po_reorder_rules_organization_id', table_name='po_reorder_rules')
    op.drop_table('po_reorder_rules')
