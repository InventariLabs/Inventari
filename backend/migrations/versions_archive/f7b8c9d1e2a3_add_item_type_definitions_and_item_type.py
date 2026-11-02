"""add_item_type_definitions_and_item_type

Revision ID: f7b8c9d1e2a3
Revises: e5f5a63a39da
Create Date: 2026-02-11 18:22:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f7b8c9d1e2a3'
down_revision = 'e5f5a63a39da'
branch_labels = None
depends_on = None


def upgrade():
    # Create item_type_definitions table
    op.create_table(
        'item_type_definitions',
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('household_id', sa.Uuid(), nullable=True),
        sa.Column('field_definitions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('code')
    )
    op.create_index('ix_item_type_definitions_household_id', 'item_type_definitions', ['household_id'])

    # Add item_type column to items table
    op.add_column('items', sa.Column('item_type', sa.String(length=50), nullable=True))
    op.create_index('ix_items_item_type', 'items', ['item_type'])

    # Alter meta_data to JSONB to support GIN index
    op.execute('ALTER TABLE items ALTER COLUMN meta_data TYPE JSONB USING meta_data::jsonb')

    # Create GIN index on meta_data for efficient JSON queries
    op.create_index(
        'ix_items_meta_data_gin',
        'items',
        ['meta_data'],
        postgresql_using='gin'
    )


def downgrade():
    op.drop_index('ix_items_meta_data_gin', table_name='items')
    op.drop_index('ix_items_item_type', table_name='items')
    op.drop_column('items', 'item_type')
    op.drop_index('ix_item_type_definitions_household_id', table_name='item_type_definitions')
    op.drop_table('item_type_definitions')
