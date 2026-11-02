"""add is_catalog_entry, warehouse_config, document_type_configs, scrap type

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-22 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'items',
        sa.Column('is_catalog_entry', sa.Boolean(), server_default='false', nullable=False),
    )
    op.create_index('ix_items_is_catalog_entry', 'items', ['is_catalog_entry'])

    op.add_column(
        'storage_locations',
        sa.Column('warehouse_config', JSONB, nullable=True),
    )

    op.create_table(
        'document_type_configs',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('document_type', sa.String(15), nullable=False),
        sa.Column(
            'default_source_location_id',
            sa.UUID(),
            sa.ForeignKey('storage_locations.id'),
            nullable=True,
        ),
        sa.Column(
            'default_target_location_id',
            sa.UUID(),
            sa.ForeignKey('storage_locations.id'),
            nullable=True,
        ),
        sa.Column(
            'sequence_format',
            sa.String(50),
            nullable=False,
            server_default='{TYPE}/{YEAR}/{SEQ:05d}',
        ),
        sa.Column('require_partner', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('allowed_fields', JSONB, nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'document_type',
            name='uq_doctype_config_org_type',
        ),
    )


def downgrade() -> None:
    op.drop_table('document_type_configs')
    op.drop_column('storage_locations', 'warehouse_config')
    op.drop_index('ix_items_is_catalog_entry', table_name='items')
    op.drop_column('items', 'is_catalog_entry')
