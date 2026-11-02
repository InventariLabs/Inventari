"""fill stock_ledger_totals - the net of the movements written before the triggers

``ledgertotals01`` keeps the totals from the next movement on; this adds up
the ones already in the ledger, once, the way the reconciliation used to on
every pass. ``stock_moves`` is held in share mode while it runs, so no
movement lands between the sum and the triggers that would have counted it.
Emptying the table first makes a second run give the same answer.

Revision ID: ledgertotals02
Revises: ledgertotals01
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'ledgertotals02'
down_revision: str | None = 'ledgertotals01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILL_SQL = """
INSERT INTO stock_ledger_totals
    (organization_id, product_template_id, storage_location_id, quantity)
SELECT organization_id, product_template_id, location_id, sum(qty)
FROM (
    SELECT organization_id, product_template_id,
           to_location_id AS location_id, quantity AS qty
    FROM stock_moves
    WHERE state = 'done' AND to_location_id IS NOT NULL
    UNION ALL
    SELECT organization_id, product_template_id, from_location_id, -quantity
    FROM stock_moves
    WHERE state = 'done' AND from_location_id IS NOT NULL
) AS sides
GROUP BY organization_id, product_template_id, location_id
"""


def upgrade() -> None:
    op.execute('LOCK TABLE stock_moves IN SHARE MODE')
    op.execute('DELETE FROM stock_ledger_totals')
    op.execute(FILL_SQL)


def downgrade() -> None:
    op.execute('DELETE FROM stock_ledger_totals')
