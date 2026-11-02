"""a record with a product needs its group's anchor: fk_items_stock_anchor

Revision ID: anchors02
Revises: anchors01
Create Date: 2026-09-27

The anchor locks a group of stock only if every write to the group takes
the lock, and ``core_api.stock.lock_async`` is what creates a missing
anchor. A door that put a record into a new group without calling it
wrote stock no lock covered, and nothing showed it. The foreign key from
``items`` to ``stock_anchors`` turns that omission into an error.

``MATCH SIMPLE``: a record without a product (``template_id IS NULL``) is
not checked. The constraint goes in ``NOT VALID``: from here on it checks
every new write, but the rows already there are checked by ``anchors03``.
Adding a foreign key takes ``SHARE ROW EXCLUSIVE`` on ``items`` and on
``stock_anchors`` (measured in ``pg_locks``): reads go through, writes to
either table wait until this transaction ends. ``NOT VALID`` keeps the
statement itself short, and ``anchors03`` commits it before the scan.

First, the anchors of groups written since ``anchors01`` by code that did
not create one are filled in, the same way ``anchors01`` filled them, so
the scan in ``anchors03`` finds every record's anchor.

``downgrade`` drops the constraint; no data changes either way.
"""

from alembic import op

revision = 'anchors02'
down_revision = 'anchors01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO stock_anchors (id, organization_id, product_template_id, storage_location_id)
        SELECT DISTINCT ON (items.organization_id, items.template_id, items.storage_location_id)
               gen_random_uuid(), items.organization_id, items.template_id,
               items.storage_location_id
        FROM items
        JOIN organizations ON organizations.id = items.organization_id
        JOIN product_templates ON product_templates.id = items.template_id
        JOIN storage_locations ON storage_locations.id = items.storage_location_id
        WHERE items.template_id IS NOT NULL
        ON CONFLICT (organization_id, product_template_id, storage_location_id) DO NOTHING
        """
    )
    op.execute(
        """
        ALTER TABLE items ADD CONSTRAINT fk_items_stock_anchor
        FOREIGN KEY (organization_id, template_id, storage_location_id)
        REFERENCES stock_anchors (organization_id, product_template_id, storage_location_id)
        MATCH SIMPLE
        NOT VALID
        """
    )


def downgrade() -> None:
    op.drop_constraint('fk_items_stock_anchor', 'items', type_='foreignkey')
