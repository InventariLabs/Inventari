"""a reservation never outgrows its grain: a constraint trigger checked at commit

Revision ID: holdguard01
Revises: ff89a60bb606
Create Date: 2026-09-28

The quant row carries ``CHECK (reserved_quantity <= quantity)``, so even a
bug in the code cannot commit a reservation of more than a batch holds: the
database refuses the transaction. Once the records are the only count, both
sides of that sentence are sums over two tables — the records of a
``(product, shelf, batch, owner)`` grain and the reservation rows of the
same grain — and a ``CHECK`` cannot read a sum.

A constraint trigger can. ``DEFERRABLE INITIALLY DEFERRED``, so it runs at
commit, when every row the transaction wrote is in place: a document that
releases its hold and then takes the stock is judged on where it ended,
not on the moment between. It fires only where a grain can come out
behind:

- a reservation row inserted, or updated in its quantity or its grain —
  the grain it now names;
- a record updated in its quantity, batch, owner, shelf, product or
  deletion flag, or deleted outright — the grain it stood in, and only when
  the change can have taken stock from it (the ``WHEN`` of the trigger,
  evaluated as the row is written, lets an increase through without
  queueing a check).

Each firing sums the reservation rows of its grain and, only if they hold
anything, the live records of the grain, counted as the records' view
counts them (``resgrain01``): a record marked deleted, or with no product,
holds nothing, and NaN is not a number. More held than there is refuses the
commit with ``check_violation`` and the name
``ck_stock_holds_within_stock``, which the API answers with a 409 in words.

It is a net, not the lock. Two transactions judge the grain on what each
can see at its own commit; the anchor lock, which every writer of a group
holds to its commit, is what makes the second one see the first.

Grains that are over-reserved already are not examined here; the next
write that could make one worse is refused, and the reconciliation shows
them in the meantime.

``downgrade`` drops the three triggers and the function.
"""

from alembic import op

revision = 'holdguard01'
down_revision = 'ff89a60bb606'
branch_labels = None
depends_on = None

# Kept here rather than imported from the application: a migration is a
# snapshot of what was done. The test databases, built by ``create_all``,
# run these same statements (``backend/conftest.py``), so the suite runs
# under the guard that ships.
GUARD_SQL = (
    """
CREATE FUNCTION stock_holds_within_stock() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    g_anchor uuid;
    g_lot uuid;
    g_owner uuid;
    anchor stock_anchors%ROWTYPE;
    held numeric;
    on_hand numeric;
BEGIN
    IF TG_TABLE_NAME = 'stock_reservations' THEN
        g_anchor := NEW.anchor_id;
        g_lot := NEW.lot_id;
        g_owner := NEW.owner_id;
    ELSE
        SELECT id INTO g_anchor FROM stock_anchors
         WHERE organization_id = OLD.organization_id
           AND product_template_id = OLD.template_id
           AND storage_location_id = OLD.storage_location_id;
        g_lot := OLD.lot_id;
        g_owner := OLD.owner_id;
    END IF;
    -- A group with no anchor has no reservation rows to hold it.
    IF g_anchor IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT coalesce(sum(quantity), 0) INTO held
      FROM stock_reservations
     WHERE anchor_id = g_anchor
       AND lot_id IS NOT DISTINCT FROM g_lot
       AND owner_id IS NOT DISTINCT FROM g_owner;
    IF held = 0 THEN
        RETURN NULL;
    END IF;

    SELECT * INTO anchor FROM stock_anchors WHERE id = g_anchor;
    SELECT coalesce(sum(nullif(quantity, 'NaN'::numeric)), 0) INTO on_hand
      FROM items
     WHERE organization_id = anchor.organization_id
       AND template_id = anchor.product_template_id
       AND storage_location_id = anchor.storage_location_id
       AND lot_id IS NOT DISTINCT FROM g_lot
       AND owner_id IS NOT DISTINCT FROM g_owner
       AND is_deleted IS FALSE;

    IF held > on_hand THEN
        RAISE EXCEPTION
            'ck_stock_holds_within_stock: % reserved of a grain holding %',
            held, on_hand
        USING ERRCODE = 'check_violation',
              CONSTRAINT = 'ck_stock_holds_within_stock',
              DETAIL = format(
                  'product %s, shelf %s, batch %s, owner %s',
                  anchor.product_template_id,
                  anchor.storage_location_id,
                  coalesce(g_lot::text, '-'),
                  coalesce(g_owner::text, '-')
              );
    END IF;
    RETURN NULL;
END $$
""",
    """
CREATE CONSTRAINT TRIGGER ck_stock_holds_within_stock
    AFTER INSERT OR UPDATE OF quantity, anchor_id, lot_id, owner_id
    ON stock_reservations
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION stock_holds_within_stock()
""",
    # The WHEN is evaluated as the row is written, not at commit: a record
    # that only gained stock queues nothing.
    """
CREATE CONSTRAINT TRIGGER ck_stock_holds_within_stock
    AFTER UPDATE OF quantity, lot_id, owner_id, storage_location_id,
        template_id, is_deleted
    ON items
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    WHEN (
        OLD.is_deleted IS FALSE
        AND OLD.template_id IS NOT NULL
        AND OLD.storage_location_id IS NOT NULL
        AND (
            NEW.is_deleted IS NOT FALSE
            OR NEW.template_id IS DISTINCT FROM OLD.template_id
            OR NEW.storage_location_id IS DISTINCT FROM OLD.storage_location_id
            OR NEW.lot_id IS DISTINCT FROM OLD.lot_id
            OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
            OR NEW.quantity IS NULL
            OR NEW.quantity = 'NaN'::numeric
            OR NEW.quantity < OLD.quantity
        )
    )
    EXECUTE FUNCTION stock_holds_within_stock()
""",
    """
CREATE CONSTRAINT TRIGGER ck_stock_holds_within_stock_on_delete
    AFTER DELETE
    ON items
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    WHEN (
        OLD.is_deleted IS FALSE
        AND OLD.template_id IS NOT NULL
        AND OLD.storage_location_id IS NOT NULL
    )
    EXECUTE FUNCTION stock_holds_within_stock()
""",
)

DROP_SQL = (
    'DROP TRIGGER IF EXISTS ck_stock_holds_within_stock_on_delete ON items',
    'DROP TRIGGER IF EXISTS ck_stock_holds_within_stock ON items',
    'DROP TRIGGER IF EXISTS ck_stock_holds_within_stock ON stock_reservations',
    'DROP FUNCTION IF EXISTS stock_holds_within_stock()',
)


def upgrade() -> None:
    for statement in GUARD_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DROP_SQL:
        op.execute(statement)
