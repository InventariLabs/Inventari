"""the quant table goes: stock and holds live on the records and the reservation rows

Revision ID: quantdrop01
Revises: stockpage01
Create Date: 2026-09-29

The one step of the one-number stock model (ADR-022) that cannot be undone
by reverting code. Until here
``stock_quants`` took a parallel write from every door, so the
reconciliation's fourth pair and the suite's drift detector could measure
each step against it; nothing reads it any more and nothing writes it after
this revision:

- the records are the stock — ``stock_quants_from_records`` sums them per
  (product, shelf, batch, owner), and has read the holds from the
  reservation rows' own grain since ``resgrain01``;
- the lock every writer of a group takes is the group's anchor
  (``stock_anchors``, ``anchors01``), never a quant;
- a reservation names its anchor, batch and owner (``resgrain01``), so
  ``stock_reservations.stock_quant_id`` goes with the table;
- a picking line names its group and batch; its ``quant_id`` column belongs
  to the documents module, whose own migration (``doc_pick_quant_gone01``)
  drops it. The foreign key it carries is dropped here, by the ``CASCADE``
  on the table: core migrations run before the modules' and cannot wait
  for them.

``downgrade`` is a rebuild, not a restore. It recreates the table with every
constraint it had and fills it from the records' view — one row per group on
a shelf, holding what the records hold and what the reservation rows hold —
then points each reservation row back at the quant of its grain. What it
cannot bring back is what only the table held: a row for a group whose
records are gone (an emptied quant), its own ``created_at``, and any quantity
the table said and the records did not, which the reconciliation's fourth
pair showed at 0 on every measured database before this revision. A database
whose holds outgrow their stock fails the rebuild on the table's own check,
rather than rebuilding a table that says so. The code that wrote the table is
gone too: after a downgrade it stands, and nothing keeps it.
"""

from alembic import op

revision = 'quantdrop01'
down_revision = 'stockpage01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('ix_reservation_quant', table_name='stock_reservations')
    op.drop_column('stock_reservations', 'stock_quant_id')
    op.execute('DROP TABLE stock_quants CASCADE')


# The table as the last revision before this one left it, constraint for
# constraint (``pg_dump --schema-only -t stock_quants`` on ``stockpage01``).
_TABLE_SQL = """
CREATE TABLE stock_quants (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    product_template_id uuid NOT NULL,
    storage_location_id uuid NOT NULL,
    lot_id uuid,
    owner_id uuid,
    quantity numeric(12,3) NOT NULL,
    reserved_quantity numeric(12,3) NOT NULL,
    removal_strategy character varying(10) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT stock_quants_pkey PRIMARY KEY (id),
    CONSTRAINT uq_quant_product_location_lot_owner UNIQUE NULLS NOT DISTINCT
        (organization_id, product_template_id, storage_location_id, lot_id, owner_id),
    CONSTRAINT ck_stock_quants_quantity_nonneg CHECK (quantity >= 0),
    CONSTRAINT ck_stock_quants_reserved_le_quantity CHECK (reserved_quantity <= quantity),
    CONSTRAINT ck_stock_quants_reserved_nonneg CHECK (reserved_quantity >= 0),
    CONSTRAINT fk_stock_quants_lot_id_stock_lots FOREIGN KEY (lot_id)
        REFERENCES stock_lots(id) ON DELETE SET NULL,
    CONSTRAINT fk_stock_quants_organization_id_organizations FOREIGN KEY (organization_id)
        REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_stock_quants_owner_id_partners FOREIGN KEY (owner_id)
        REFERENCES partners(id) ON DELETE SET NULL,
    CONSTRAINT fk_stock_quants_product_template_id_product_templates
        FOREIGN KEY (product_template_id) REFERENCES product_templates(id) ON DELETE CASCADE,
    CONSTRAINT fk_stock_quants_storage_location_id_storage_locations
        FOREIGN KEY (storage_location_id) REFERENCES storage_locations(id) ON DELETE CASCADE
);
CREATE INDEX ix_quant_org_template_loc
    ON stock_quants (organization_id, product_template_id, storage_location_id);
CREATE INDEX ix_stock_quants_lot_id ON stock_quants (lot_id);
CREATE INDEX ix_stock_quants_organization_id ON stock_quants (organization_id);
CREATE INDEX ix_stock_quants_product_template_id ON stock_quants (product_template_id);
CREATE INDEX ix_stock_quants_storage_location_id ON stock_quants (storage_location_id);
"""

# One quant per group on a shelf, as the records and the holds tell it. The
# view's id is the group's own, stable across reads, so it serves as the row's.
_REBUILD_SQL = """
INSERT INTO stock_quants (
    id, organization_id, product_template_id, storage_location_id, lot_id,
    owner_id, quantity, reserved_quantity, removal_strategy, created_at,
    updated_at
)
SELECT v.id, v.organization_id, v.product_template_id, v.storage_location_id,
       v.lot_id, v.owner_id, v.quantity, v.reserved_quantity, v.removal_strategy,
       coalesce(v.created_at, now()), coalesce(v.updated_at, now())
FROM stock_quants_from_records v
WHERE v.storage_location_id IS NOT NULL
"""

# Every reservation row back on the quant of the grain it names.
_POINT_SQL = """
UPDATE stock_reservations r
   SET stock_quant_id = q.id
  FROM stock_anchors a, stock_quants q
 WHERE a.id = r.anchor_id
   AND q.organization_id = a.organization_id
   AND q.product_template_id = a.product_template_id
   AND q.storage_location_id = a.storage_location_id
   AND q.lot_id IS NOT DISTINCT FROM r.lot_id
   AND q.owner_id IS NOT DISTINCT FROM r.owner_id
"""


def downgrade() -> None:
    op.execute(_TABLE_SQL)
    op.execute(_REBUILD_SQL)
    op.execute('ALTER TABLE stock_reservations ADD COLUMN stock_quant_id uuid')
    op.execute(_POINT_SQL)
    op.execute(
        'ALTER TABLE stock_reservations ALTER COLUMN stock_quant_id SET NOT NULL'
    )
    op.execute(
        'ALTER TABLE stock_reservations ADD CONSTRAINT '
        'stock_reservations_stock_quant_id_fkey FOREIGN KEY (stock_quant_id) '
        'REFERENCES stock_quants(id) ON DELETE CASCADE'
    )
    op.create_index('ix_reservation_quant', 'stock_reservations', ['stock_quant_id'])
