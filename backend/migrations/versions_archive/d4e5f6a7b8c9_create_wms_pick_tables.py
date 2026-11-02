"""create wms_pick_sessions and wms_pick_lines tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-22 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wms_pick_sessions',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'document_id',
            UUID(),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'assigned_to',
            UUID(),
            sa.ForeignKey('users.id'),
            nullable=True,
        ),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column(
            'started_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('meta_data', JSONB, nullable=True),
    )

    op.create_table(
        'wms_pick_lines',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column(
            'session_id',
            UUID(),
            sa.ForeignKey('wms_pick_sessions.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'document_line_id',
            UUID(),
            sa.ForeignKey('document_lines.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'quant_id',
            UUID(),
            sa.ForeignKey('stock_quants.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('pick_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'status', sa.String(20), nullable=False, server_default='pending'
        ),
        sa.Column(
            'picked_quantity',
            sa.Numeric(12, 3),
            nullable=False,
            server_default='0',
        ),
        sa.Column('bin_location', sa.String(255), nullable=True),
        sa.Column('product_name', sa.String(255), nullable=True),
        sa.Column('lot_name', sa.String(100), nullable=True),
        sa.Column(
            'expected_quantity', sa.Numeric(12, 3), nullable=False
        ),
        sa.Column('uom_symbol', sa.String(10), nullable=True),
    )

    op.create_index(
        'ix_wps_org_status',
        'wms_pick_sessions',
        ['organization_id', 'status'],
    )
    op.create_index(
        'ix_wpl_session_status',
        'wms_pick_lines',
        ['session_id', 'status'],
    )


def downgrade() -> None:
    op.drop_index('ix_wpl_session_status', table_name='wms_pick_lines')
    op.drop_index('ix_wps_org_status', table_name='wms_pick_sessions')
    op.drop_table('wms_pick_lines')
    op.drop_table('wms_pick_sessions')
