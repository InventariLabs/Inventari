"""items carry their batch and owner: lot_id, owner_id and the stock-group index

Revision ID: lotrec01
Revises: 5d37c6598bf8
Create Date: 2026-09-25

A quant is keyed by (organization, product, shelf, batch, owner); a record
carried only the first three, so nothing said which of a shelf's records was
which batch, or whose. The stock model is moving to one record per batch per
owner, so that the records' quantities can become the only stock number and
the quant their sum. This adds the two columns, nullable, and the index that
sums a record group the way a quant is keyed. Assigning the existing records
is a data migration of its own (``lotrec02``).

``downgrade`` drops the index and both columns; no record's quantity changes
either way.
"""

import sqlalchemy as sa
from alembic import op

revision = 'lotrec01'
down_revision = '5d37c6598bf8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('items', sa.Column('lot_id', sa.Uuid(), nullable=True))
    op.add_column('items', sa.Column('owner_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_items_lot_id',
        'items',
        'stock_lots',
        ['lot_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_items_owner_id',
        'items',
        'partners',
        ['owner_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_items_stock_group',
        'items',
        [
            'organization_id',
            'template_id',
            'storage_location_id',
            'lot_id',
            'owner_id',
        ],
    )


def downgrade() -> None:
    op.drop_index('ix_items_stock_group', table_name='items')
    op.drop_constraint('fk_items_owner_id', 'items', type_='foreignkey')
    op.drop_constraint('fk_items_lot_id', 'items', type_='foreignkey')
    op.drop_column('items', 'owner_id')
    op.drop_column('items', 'lot_id')
