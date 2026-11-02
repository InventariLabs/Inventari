"""add stock_moves table for explicit WMS movement ledger

Revision ID: stockmove01
Revises: moveproddate01
Create Date: 2026-06-23

The StockMove entity is the authoritative record of every physical
stock movement (receipt, delivery, transfer, adjustment).  ItemHistory
remains for per-item audit but cannot answer movement-history queries
needed for analytics, FIFO/FEFO traceability, and GS1/WMS compliance.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'stockmove01'
down_revision: str | None = 'moveproddate01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'stock_moves',
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
            'from_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'to_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'lot_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('stock_lots.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('state', sa.String(20), nullable=False, server_default='done'),
        sa.Column('reference_type', sa.String(20), nullable=True),
        # Polymorphic — no FK constraint; target table depends on reference_type.
        sa.Column('reference_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
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
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        'ix_stock_moves_org_template',
        'stock_moves',
        ['organization_id', 'product_template_id'],
    )
    op.create_index('ix_stock_moves_from_loc', 'stock_moves', ['from_location_id'])
    op.create_index('ix_stock_moves_to_loc', 'stock_moves', ['to_location_id'])
    op.create_index(
        'ix_stock_moves_reference',
        'stock_moves',
        ['reference_type', 'reference_id'],
    )
    op.create_index('ix_stock_moves_completed_at', 'stock_moves', ['completed_at'])
    op.create_index('ix_stock_moves_created_at', 'stock_moves', ['created_at'])
    op.create_index(
        'ix_stock_moves_organization_id', 'stock_moves', ['organization_id']
    )
    op.create_index(
        'ix_stock_moves_product_template_id',
        'stock_moves',
        ['product_template_id'],
    )
    op.create_index('ix_stock_moves_lot_id', 'stock_moves', ['lot_id'])
    op.create_index('ix_stock_moves_created_by', 'stock_moves', ['created_by'])

    op.create_check_constraint(
        'ck_stock_moves_qty_positive', 'stock_moves', 'quantity > 0'
    )
    op.create_check_constraint(
        'ck_stock_moves_at_least_one_location',
        'stock_moves',
        'from_location_id IS NOT NULL OR to_location_id IS NOT NULL',
    )


def downgrade() -> None:
    op.drop_constraint('ck_stock_moves_at_least_one_location', 'stock_moves')
    op.drop_constraint('ck_stock_moves_qty_positive', 'stock_moves')
    op.drop_index('ix_stock_moves_created_by', table_name='stock_moves')
    op.drop_index('ix_stock_moves_lot_id', table_name='stock_moves')
    op.drop_index('ix_stock_moves_product_template_id', table_name='stock_moves')
    op.drop_index('ix_stock_moves_organization_id', table_name='stock_moves')
    op.drop_index('ix_stock_moves_completed_at', table_name='stock_moves')
    op.drop_index('ix_stock_moves_created_at', table_name='stock_moves')
    op.drop_index('ix_stock_moves_reference', table_name='stock_moves')
    op.drop_index('ix_stock_moves_to_loc', table_name='stock_moves')
    op.drop_index('ix_stock_moves_from_loc', table_name='stock_moves')
    op.drop_index('ix_stock_moves_org_template', table_name='stock_moves')
    op.drop_table('stock_moves')
