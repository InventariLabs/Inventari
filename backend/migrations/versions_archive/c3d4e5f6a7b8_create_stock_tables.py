"""create stock_lots, stock_packages, stock_quants tables

Revision ID: c3d4e5f6a7b8
Revises: b2a1c3d4e5f6
Create Date: 2026-04-22 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2a1c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stock_lots',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            index=True,
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            index=True,
            nullable=False,
        ),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('is_serial', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True, index=True),
        sa.Column('production_date', sa.Date(), nullable=True),
        sa.Column('use_by_date', sa.Date(), nullable=True),
        sa.Column(
            'removal_strategy',
            sa.String(10),
            server_default='FIFO',
            nullable=False,
        ),
        sa.Column(
            'status', sa.String(20), server_default='active', nullable=False
        ),
        sa.Column('meta_data', JSONB(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            'name',
            name='uq_lot_org_product_name',
        ),
    )
    op.create_index(
        'ix_lot_org_expiry', 'stock_lots', ['organization_id', 'expiry_date']
    )

    op.create_table(
        'stock_packages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            index=True,
            nullable=False,
        ),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column(
            'parent_id',
            UUID(as_uuid=True),
            sa.ForeignKey('stock_packages.id'),
            nullable=True,
        ),
        sa.Column(
            'storage_location_id',
            UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('meta_data', JSONB(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        'stock_quants',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            index=True,
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            index=True,
            nullable=False,
        ),
        sa.Column(
            'storage_location_id',
            UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            index=True,
            nullable=False,
        ),
        sa.Column(
            'lot_id',
            UUID(as_uuid=True),
            sa.ForeignKey('stock_lots.id', ondelete='SET NULL'),
            index=True,
            nullable=True,
        ),
        sa.Column(
            'package_id',
            UUID(as_uuid=True),
            sa.ForeignKey('stock_packages.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'owner_id',
            UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'quantity',
            sa.Numeric(12, 3),
            server_default=sa.text('0'),
            nullable=False,
        ),
        sa.Column(
            'reserved_quantity',
            sa.Numeric(12, 3),
            server_default=sa.text('0'),
            nullable=False,
        ),
        sa.Column(
            'removal_strategy',
            sa.String(10),
            server_default='FIFO',
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            'storage_location_id',
            'lot_id',
            'package_id',
            name='uq_quant_product_location_lot_package',
        ),
    )
    op.create_index(
        'ix_quant_org_template_loc',
        'stock_quants',
        ['organization_id', 'product_template_id', 'storage_location_id'],
    )

    op.execute(
        """
        INSERT INTO stock_lots (id, organization_id, product_template_id, name, is_serial, expiry_date, production_date, status, removal_strategy, created_at)
        SELECT
            gen_random_uuid(),
            i.organization_id,
            i.template_id,
            COALESCE(i.serial_number, i.lot_number),
            CASE WHEN i.serial_number IS NOT NULL THEN true ELSE false END,
            i.expiry_date,
            i.production_date,
            'active',
            'FIFO',
            now()
        FROM items i
        WHERE i.lot_number IS NOT NULL
          AND i.template_id IS NOT NULL
          AND i.is_deleted = false
          AND NOT EXISTS (
              SELECT 1 FROM stock_lots sl
              WHERE sl.organization_id = i.organization_id
                AND sl.product_template_id = i.template_id
                AND sl.name = COALESCE(i.serial_number, i.lot_number)
          )
        """
    )

    op.execute(
        """
        INSERT INTO stock_quants (id, organization_id, product_template_id, storage_location_id, lot_id, quantity, reserved_quantity, removal_strategy, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            i.organization_id,
            i.template_id,
            i.storage_location_id,
            sl.id,
            COALESCE(i.quantity, 0),
            0,
            'FIFO',
            now(),
            now()
        FROM items i
        LEFT JOIN stock_lots sl
            ON sl.organization_id = i.organization_id
            AND sl.product_template_id = i.template_id
            AND sl.name = COALESCE(i.serial_number, i.lot_number)
        WHERE i.template_id IS NOT NULL
          AND i.storage_location_id IS NOT NULL
          AND i.is_deleted = false
          AND NOT EXISTS (
              SELECT 1 FROM stock_quants sq
              WHERE sq.organization_id = i.organization_id
                AND sq.product_template_id = i.template_id
                AND sq.storage_location_id = i.storage_location_id
                AND (sq.lot_id = sl.id OR (sq.lot_id IS NULL AND sl.id IS NULL))
                AND sq.package_id IS NULL
          )
        """
    )

    op.execute(
        """
        SELECT COUNT(*) INTO _ FROM (
            SELECT
                sq.product_template_id,
                sq.storage_location_id,
                SUM(sq.quantity) as quant_qty
            FROM stock_quants sq
            GROUP BY sq.product_template_id, sq.storage_location_id
        ) q
        INNER JOIN (
            SELECT
                i.template_id,
                i.storage_location_id,
                SUM(i.quantity) as item_qty
            FROM items i
            WHERE i.is_deleted = false
              AND i.template_id IS NOT NULL
              AND i.storage_location_id IS NOT NULL
            GROUP BY i.template_id, i.storage_location_id
        ) it ON q.product_template_id = it.template_id
             AND q.storage_location_id = it.storage_location_id
        WHERE q.quant_qty != it.item_qty
        """
    )


def downgrade() -> None:
    op.drop_table('stock_quants')
    op.drop_table('stock_packages')
    op.drop_table('stock_lots')
