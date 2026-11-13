"""take the ledger totals a removed movement touches in key order

``ledgertotals01`` keeps ``stock_ledger_totals`` with triggers on
``stock_moves``. Their adding half writes the totals' rows in key order, so two
statements over the same groups wait for each other rather than deadlock.
Their subtracting half updated the rows in whatever order its join produced.
It runs whenever movements are deleted, and whenever they are rewritten
because a shelf, batch, partner or user they name was deleted and the
foreign key set the reference to NULL. Two such statements over the same
groups could each take a row the other then waited for.

The subtracting half now locks its rows in key order (``ORDER BY ... FOR
UPDATE``) before it subtracts, the order the adding half writes in. Nothing
else in the function changes: the same sums, and a removed movement still
only subtracts from a row that is still there.

Revision ID: ledgertotals03
Revises: auditidx03
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'ledgertotals03'
down_revision: str | None = 'auditidx03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADDED = """
        IF TG_OP IN ('INSERT', 'UPDATE') THEN
            INSERT INTO stock_ledger_totals AS t
                (organization_id, product_template_id, storage_location_id, quantity)
            SELECT organization_id, product_template_id, location_id, sum(qty)
            FROM (
                SELECT organization_id, product_template_id,
                       to_location_id AS location_id, quantity AS qty
                FROM new_moves
                WHERE state = 'done' AND to_location_id IS NOT NULL
                UNION ALL
                SELECT organization_id, product_template_id,
                       from_location_id, -quantity
                FROM new_moves
                WHERE state = 'done' AND from_location_id IS NOT NULL
            ) AS sides
            GROUP BY organization_id, product_template_id, location_id
            ORDER BY organization_id, product_template_id, location_id
            ON CONFLICT (organization_id, product_template_id, storage_location_id)
            DO UPDATE SET quantity = t.quantity + EXCLUDED.quantity;
        END IF;
"""

_GONE = """
                SELECT organization_id, product_template_id, location_id,
                       sum(qty) AS qty
                FROM (
                    SELECT organization_id, product_template_id,
                           to_location_id AS location_id, quantity AS qty
                    FROM old_moves
                    WHERE state = 'done' AND to_location_id IS NOT NULL
                    UNION ALL
                    SELECT organization_id, product_template_id,
                           from_location_id, -quantity
                    FROM old_moves
                    WHERE state = 'done' AND from_location_id IS NOT NULL
                ) AS sides
                GROUP BY organization_id, product_template_id, location_id
"""

#: The rows are locked in key order first (``locked``, materialised because it
#: locks), and only then subtracted from.
_SUBTRACTED_IN_KEY_ORDER = f"""
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            WITH gone AS ({_GONE}
            ), locked AS (
                SELECT t.organization_id, t.product_template_id,
                       t.storage_location_id, gone.qty
                FROM stock_ledger_totals AS t
                JOIN gone
                  ON t.organization_id = gone.organization_id
                 AND t.product_template_id = gone.product_template_id
                 AND t.storage_location_id = gone.location_id
                ORDER BY t.organization_id, t.product_template_id,
                         t.storage_location_id
                FOR UPDATE OF t
            )
            UPDATE stock_ledger_totals AS t
            SET quantity = t.quantity - locked.qty
            FROM locked
            WHERE t.organization_id = locked.organization_id
              AND t.product_template_id = locked.product_template_id
              AND t.storage_location_id = locked.storage_location_id;
        END IF;
"""

#: ``ledgertotals01``'s subtracting half, restored by the downgrade.
_SUBTRACTED_IN_ANY_ORDER = f"""
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            UPDATE stock_ledger_totals AS t
            SET quantity = t.quantity - gone.qty
            FROM ({_GONE}
            ) AS gone
            WHERE t.organization_id = gone.organization_id
              AND t.product_template_id = gone.product_template_id
              AND t.storage_location_id = gone.location_id;
        END IF;
"""


def _function(subtracted: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION stock_ledger_totals_follow_moves() RETURNS trigger
    LANGUAGE plpgsql SET search_path = public AS $$
    BEGIN{_ADDED}{subtracted}
        RETURN NULL;
    END
    $$
    """


#: Run verbatim by the test databases after ``ledgertotals01``'s statements
#: (``conftest.py``), so the suite is kept by what ships.
FUNCTION_SQL = _function(_SUBTRACTED_IN_KEY_ORDER)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)


def downgrade() -> None:
    op.execute(_function(_SUBTRACTED_IN_ANY_ORDER))
