"""remove item types - the table and the column that named one

Item types had no screen, no row in any organization and no module that
declared one; keeping their routes and table would have shipped an API
concept nobody can reach as a contract. The table goes, and so does
``items.item_type``, the free-text code that pointed at it.

Revision ID: itemtypes01
Revises: baseline_002
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'itemtypes01'
down_revision: str | None = 'baseline_002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f('ix_items_item_type'), table_name='items')
    op.drop_column('items', 'item_type')
    op.drop_table('item_type_definitions')


def downgrade() -> None:
    op.create_table(
        'item_type_definitions',
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=True),
        sa.Column('module_name', sa.String(length=50), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column(
            'allowed_system_fields',
            sa.JSON(),
            server_default='["brand", "barcode", "quantity", "unit"]',
            nullable=False,
        ),
        sa.Column('field_definitions', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('code'),
    )
    op.create_index(
        op.f('ix_item_type_definitions_is_active'),
        'item_type_definitions',
        ['is_active'],
    )
    op.create_index(
        op.f('ix_item_type_definitions_module_name'),
        'item_type_definitions',
        ['module_name'],
    )
    op.create_index(
        op.f('ix_item_type_definitions_organization_id'),
        'item_type_definitions',
        ['organization_id'],
    )
    op.add_column('items', sa.Column('item_type', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_items_item_type'), 'items', ['item_type'])
