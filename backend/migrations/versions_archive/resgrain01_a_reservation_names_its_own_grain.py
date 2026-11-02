"""a reservation names its own grain: stock_reservations.anchor_id, lot_id, owner_id

Revision ID: resgrain01
Revises: anchors01
Create Date: 2026-09-27

A reservation row names the quant it holds stock on, and everything else it
is about — the product, the shelf, the batch, the owner — is read off that
quant: by the records' view (``quantview01``) and by every lock that looks
for a document's holds. The quants go away once the records are the only
count, and a row that knows its place only through one would lose it.

So the row carries its grain itself: the anchor of its group (a product on
a shelf, ``anchors01``), the batch and the owner, filled here from the quant
it points at. ``stock_quant_id`` stays and is still written beside them.

- A reservation's group gets its anchor here if it has none yet. The anchors
  migration filled one for every group a quant named, so this finds nothing
  on an instance that took every write through the application since then.
- A row whose group can have no anchor — a product, shelf or organization
  that no longer exists, which only an instance that started from the first
  baseline, with no foreign keys, can hold — is deleted: it holds stock of
  nothing, and an anchor's own keys would refuse it.
- The view reads the held quantity by the row's own columns.

``downgrade`` puts the view back as ``quantview01`` built it and drops the
three columns; the rows deleted above do not come back.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'resgrain01'
down_revision = 'anchors01'
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
    SELECT a.organization_id,
           a.product_template_id,
           a.storage_location_id,
           r.lot_id,
           r.owner_id,
           NULL::numeric,
           r.quantity,
           r.created_at,
           r.created_at
    FROM stock_reservations r
    JOIN stock_anchors a ON a.id = r.anchor_id
) AS sides
GROUP BY sides.organization_id,
         sides.product_template_id,
         sides.storage_location_id,
         sides.lot_id,
         sides.owner_id
"""

# The view as ``quantview01`` created it, for ``downgrade``.
_QUANTVIEW01_SQL = """
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
    op.add_column(
        'stock_reservations',
        sa.Column('anchor_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'stock_reservations',
        sa.Column('lot_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'stock_reservations',
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        INSERT INTO stock_anchors (id, organization_id, product_template_id, storage_location_id)
        SELECT gen_random_uuid(), groups.organization_id, groups.product_template_id,
               groups.storage_location_id
        FROM (
            SELECT DISTINCT q.organization_id, q.product_template_id, q.storage_location_id
            FROM stock_reservations r
            JOIN stock_quants q ON q.id = r.stock_quant_id
        ) AS groups
        JOIN organizations ON organizations.id = groups.organization_id
        JOIN product_templates ON product_templates.id = groups.product_template_id
        JOIN storage_locations ON storage_locations.id = groups.storage_location_id
        ON CONFLICT (organization_id, product_template_id, storage_location_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE stock_reservations r
        SET anchor_id = a.id, lot_id = q.lot_id, owner_id = q.owner_id
        FROM stock_quants q
        JOIN stock_anchors a
          ON a.organization_id = q.organization_id
         AND a.product_template_id = q.product_template_id
         AND a.storage_location_id = q.storage_location_id
        WHERE q.id = r.stock_quant_id
        """
    )
    op.execute('DELETE FROM stock_reservations WHERE anchor_id IS NULL')
    op.alter_column('stock_reservations', 'anchor_id', nullable=False)
    op.create_foreign_key(
        'stock_reservations_anchor_id_fkey',
        'stock_reservations',
        'stock_anchors',
        ['anchor_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'stock_reservations_lot_id_fkey',
        'stock_reservations',
        'stock_lots',
        ['lot_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'stock_reservations_owner_id_fkey',
        'stock_reservations',
        'partners',
        ['owner_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_reservation_anchor', 'stock_reservations', ['anchor_id'])
    op.execute('DROP VIEW IF EXISTS stock_quants_from_records')
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute('DROP VIEW IF EXISTS stock_quants_from_records')
    op.execute(_QUANTVIEW01_SQL)
    op.drop_index('ix_reservation_anchor', table_name='stock_reservations')
    op.drop_constraint(
        'stock_reservations_owner_id_fkey', 'stock_reservations', type_='foreignkey'
    )
    op.drop_constraint(
        'stock_reservations_lot_id_fkey', 'stock_reservations', type_='foreignkey'
    )
    op.drop_constraint(
        'stock_reservations_anchor_id_fkey', 'stock_reservations', type_='foreignkey'
    )
    op.drop_column('stock_reservations', 'owner_id')
    op.drop_column('stock_reservations', 'lot_id')
    op.drop_column('stock_reservations', 'anchor_id')
