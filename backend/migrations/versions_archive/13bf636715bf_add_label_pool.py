"""add_label_pool

Revision ID: 13bf636715bf
Revises: 568c2191c93b
Create Date: 2026-01-30 17:34:03.698721

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13bf636715bf'
down_revision: Union[str, None] = '568c2191c93b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Label pool table
    op.create_table(
        'label_pool',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('short_code', sa.String(20), nullable=False),
        sa.Column('is_assigned', sa.Boolean(), default=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.Column('item_id', sa.Uuid(), nullable=True),
        sa.Column('household_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('printed_at', sa.DateTime(), nullable=True),
        sa.Column('scan_count', sa.Integer(), default=0),
        sa.Column('last_scanned_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )
    op.create_index('ix_label_pool_short_code', 'label_pool', ['short_code'], unique=True)
    op.create_index('ix_label_pool_is_assigned', 'label_pool', ['is_assigned'])
    op.create_index('ix_label_pool_household_id', 'label_pool', ['household_id'])

    # Extend items table
    op.add_column('items', sa.Column('label_code', sa.String(20), nullable=True))
    op.create_foreign_key('fk_items_label_code', 'items', 'label_pool', ['label_code'], ['short_code'])


def downgrade() -> None:
    op.drop_constraint('fk_items_label_code', 'items', type_='foreignkey')
    op.drop_column('items', 'label_code')
    op.drop_index('ix_label_pool_household_id', table_name='label_pool')
    op.drop_index('ix_label_pool_is_assigned', table_name='label_pool')
    op.drop_index('ix_label_pool_short_code', table_name='label_pool')
    op.drop_table('label_pool')
