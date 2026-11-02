"""putaway capacity: per-product shelf limits and the single-product switch.

Revision ID: doc_putaway_capacity01
Revises: doc_line_target01
Create Date: 2026-09-16

A putaway rule about to fill a shelf could not know how much the shelf
holds, and the company overview had nothing to show occupancy from. The
capacity lives beside the rule it sharpens, in the documents module — the
same precedent as ReorderRule living in purchase_orders — so the Core
stays neutral and a home without the documents module loses nothing.

Two tables: one row per (location, product) naming the most the shelf
holds of that product in its stock unit, and one per location saying
whether the shelf takes a single product only or a mix. A location with
no rows behaves exactly as before: no limit.

Downgrade drops both tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_putaway_capacity01'
down_revision: str | None = 'doc_line_target01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'putaway_capacity',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'location_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('max_quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'location_id',
            'product_template_id',
            name='uq_putaway_capacity_org_loc_product',
        ),
    )
    op.create_index(
        'ix_putaway_capacity_org',
        'putaway_capacity',
        ['organization_id'],
    )
    op.create_table(
        'putaway_location_settings',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'location_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'single_product',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint(
            'organization_id',
            'location_id',
            name='uq_putaway_location_settings_org_loc',
        ),
    )


def downgrade() -> None:
    op.drop_table('putaway_location_settings')
    op.drop_index('ix_putaway_capacity_org', table_name='putaway_capacity')
    op.drop_table('putaway_capacity')
