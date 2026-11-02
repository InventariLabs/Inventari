"""the stock page reads the anchors: the group index carries the quantity, places by name

Revision ID: stockpage01
Revises: holdguard01
Create Date: 2026-09-29

The ``/stock-quants`` page took its rows from the quant table — which groups
exist, in what order, how many — and summed what each holds from the
records. The table is going, so the rows now come from the anchors, each
anchor's records grouped by batch and owner beside it, and the count comes
straight off the records. Two indexes make that as quick as the table was
(100 000 records: the first page 40 ms -> 22 ms):

- ``ix_items_stock_group`` keeps its key and carries ``quantity`` and
  ``is_deleted`` beside it, so counting the groups that hold anything, and
  summing one anchor's groups, are index-only reads;
- ``ix_storage_locations_org_name`` lets the page walk the places in name
  order and stop once it is full, instead of sorting every anchor of the
  organization to print fifty rows.

``downgrade`` puts the group index back without the extra columns and drops
the place index.
"""

from alembic import op

revision = 'stockpage01'
down_revision = 'holdguard01'
branch_labels = None
depends_on = None

_GROUP_KEY = [
    'organization_id',
    'template_id',
    'storage_location_id',
    'lot_id',
    'owner_id',
]


def upgrade() -> None:
    op.drop_index('ix_items_stock_group', table_name='items')
    op.create_index(
        'ix_items_stock_group',
        'items',
        _GROUP_KEY,
        postgresql_include=['quantity', 'is_deleted'],
    )
    op.create_index(
        'ix_storage_locations_org_name',
        'storage_locations',
        ['organization_id', 'name'],
    )


def downgrade() -> None:
    op.drop_index('ix_storage_locations_org_name', table_name='storage_locations')
    op.drop_index('ix_items_stock_group', table_name='items')
    op.create_index('ix_items_stock_group', 'items', _GROUP_KEY)
