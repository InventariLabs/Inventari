"""add notifications and item_type_definitions tables

Revision ID: 226a3ef74b96
Revises: 0a010f3ac3fb
Create Date: 2026-05-13 18:29:46.173542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '226a3ef74b96'  # noqa: F841 — read by Alembic runtime
down_revision: Union[str, None] = 'cd81ebba893d'  # noqa: F841
branch_labels: Union[str, Sequence[str], None] = None  # noqa: F841
depends_on: Union[str, Sequence[str], None] = None  # noqa: F841


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'item_type_definitions' not in existing_tables:
        op.create_table('item_type_definitions',
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=True),
        sa.Column('module_name', sa.String(length=50), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('allowed_system_fields', sa.JSON(), server_default='["brand", "barcode", "quantity", "unit"]', nullable=False),
        sa.Column('field_definitions', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('code')
        )
        op.create_index(op.f('ix_item_type_definitions_is_active'), 'item_type_definitions', ['is_active'], unique=False)
        op.create_index(op.f('ix_item_type_definitions_module_name'), 'item_type_definitions', ['module_name'], unique=False)
        op.create_index(op.f('ix_item_type_definitions_organization_id'), 'item_type_definitions', ['organization_id'], unique=False)
    else:
        existing_cols = {c['name'] for c in inspector.get_columns('item_type_definitions')}
        if 'household_id' in existing_cols and 'organization_id' not in existing_cols:
            op.add_column('item_type_definitions', sa.Column('organization_id', sa.Uuid(), nullable=True))
            op.create_index(op.f('ix_item_type_definitions_organization_id'), 'item_type_definitions', ['organization_id'], unique=False)
            op.drop_constraint('item_type_definitions_household_id_fkey', 'item_type_definitions', type_='foreignkey')
            op.create_foreign_key('item_type_definitions_organization_id_fkey', 'item_type_definitions', 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')
            op.drop_index('ix_item_type_definitions_household_id', table_name='item_type_definitions')
            op.drop_column('item_type_definitions', 'household_id')
        if 'module_name' not in existing_cols:
            op.add_column('item_type_definitions', sa.Column('module_name', sa.String(length=50), nullable=True))
            op.create_index(op.f('ix_item_type_definitions_module_name'), 'item_type_definitions', ['module_name'], unique=False)
        if 'is_system' not in existing_cols:
            op.add_column('item_type_definitions', sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'))
        if 'is_active' not in existing_cols:
            op.add_column('item_type_definitions', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))
            op.create_index(op.f('ix_item_type_definitions_is_active'), 'item_type_definitions', ['is_active'], unique=False)
        if 'allowed_system_fields' not in existing_cols:
            op.add_column('item_type_definitions', sa.Column('allowed_system_fields', sa.JSON(), server_default='["brand", "barcode", "quantity", "unit"]', nullable=False))

    if 'notifications' not in existing_tables:
        op.create_table('notifications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('content', sa.String(length=1000), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('link', sa.String(length=255), nullable=True),
        sa.Column('meta_data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()
    if 'notifications' in existing_tables:
        op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
        op.drop_table('notifications')
    if 'item_type_definitions' in existing_tables:
        op.drop_index(op.f('ix_item_type_definitions_organization_id'), table_name='item_type_definitions')
        op.drop_index(op.f('ix_item_type_definitions_module_name'), table_name='item_type_definitions')
        op.drop_index(op.f('ix_item_type_definitions_is_active'), table_name='item_type_definitions')
        op.drop_table('item_type_definitions')
