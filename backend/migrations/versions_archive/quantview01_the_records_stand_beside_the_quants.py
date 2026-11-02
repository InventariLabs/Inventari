"""the records stand beside the quants: the view stock_quants_from_records

Revision ID: quantview01
Revises: lotrec02
Create Date: 2026-09-26

A record now names its batch and owner (``lotrec01``/``lotrec02``) and every
write keeps them, so the records of one ``(organization, product, shelf,
batch, owner)`` group, summed, should say what that group's quant says, row
for row. This view is that sum, with the quant table's columns: the on-hand
quantity from the records, the reserved quantity from the reservation rows.

Nothing reads stock from it yet. It stands beside the table so that the
reconciliation report and the suite's drift detector can compare the two;
the table still takes every write.

- ``quantity`` sums the live records that have a product, the set the
  reconciliation's first pair counts, with a NaN left out rather than
  allowed to become the sum.
- ``reserved_quantity`` sums ``stock_reservations``. A reservation row names
  its quant, not its group, so the group's key is read off that quant; none
  of the quant's numbers are.
- ``removal_strategy`` is the table column's only value: nothing writes a
  quant's own strategy, the removal order comes from the product or the call.
- ``id`` is derived from the group's key, so it is stable for a group, but it
  is not the quant's id.

A group with records and no reservations, or with reservations and no
records, is still one row: the two sides are put together with ``UNION ALL``
and grouped, because a ``FULL JOIN`` on keys that may be NULL (the batch, the
owner) is one PostgreSQL refuses to plan.

A later migration that changes the type of, or drops, a column this view
reads (on ``items``, ``stock_quants`` or ``stock_reservations``) has to drop
the view first and create it again after.

``downgrade`` drops the view; no row of any table changes either way.
"""

from alembic import op

revision = 'quantview01'
down_revision = 'lotrec02'
branch_labels = None
depends_on = None

# Kept here rather than imported from the application: a migration is a
# snapshot of what was done. The test databases, built by ``create_all``,
# run this same statement (``backend/conftest.py``), so the suite exercises
# the view that ships rather than a copy of it.
VIEW_SQL = """
CREATE VIEW stock_quants_from_records AS
SELECT md5(
           sides.organization_id::text
           || '/' || sides.product_template_id::text
           || '/' || coalesce(sides.storage_location_id::text, '-')
           || '/' || coalesce(sides.lot_id::text, '-')
           || '/' || coalesce(sides.owner_id::text, '-')
       )::uuid AS id,
       sides.organization_id,
       sides.product_template_id,
       sides.storage_location_id,
       sides.lot_id,
       sides.owner_id,
       coalesce(sum(sides.quantity), 0)::numeric(12, 3) AS quantity,
       coalesce(sum(sides.reserved_quantity), 0)::numeric(12, 3) AS reserved_quantity,
       'FIFO'::varchar(10) AS removal_strategy,
       min(sides.created_at) AS created_at,
       max(sides.updated_at) AS updated_at
FROM (
    SELECT i.organization_id,
           i.template_id AS product_template_id,
           i.storage_location_id,
           i.lot_id,
           i.owner_id,
           nullif(i.quantity, 'NaN'::numeric) AS quantity,
           NULL::numeric AS reserved_quantity,
           i.created_at,
           i.updated_at
    FROM items i
    WHERE i.is_deleted IS FALSE AND i.template_id IS NOT NULL
    UNION ALL
    SELECT q.organization_id,
           q.product_template_id,
           q.storage_location_id,
           q.lot_id,
           q.owner_id,
           NULL::numeric,
           r.quantity,
           r.created_at,
           r.created_at
    FROM stock_reservations r
    JOIN stock_quants q ON q.id = r.stock_quant_id
) AS sides
GROUP BY sides.organization_id,
         sides.product_template_id,
         sides.storage_location_id,
         sides.lot_id,
         sides.owner_id
"""


def upgrade() -> None:
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute('DROP VIEW IF EXISTS stock_quants_from_records')
