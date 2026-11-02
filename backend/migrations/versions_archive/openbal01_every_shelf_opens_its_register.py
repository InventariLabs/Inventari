"""every shelf opens its register: an explicit opening balance

Revision ID: openbal01
Revises: seedfield01
Create Date: 2026-09-24

Every organization keeps quants and movements (decided 2026-09-24). The
bridge used to write them only where a module that keeps a register was
enabled, so an organization without one holds its stock on its records alone,
and so does any shelf whose records predate the register. The bridge would
fill such a shelf lazily, on the first change — the heal whose guesses were
the drift of their own. This posts the opening instead, once and in
the open.

For every ``(organization, product, shelf)`` whose live records hold stock and
which has no quant at all:

- a batch-less quant holding what those records hold;
- a movement into the shelf of the same quantity, marked ``opening_balance``,
  so the register can tell the opening from a change anybody made;
- one cost layer per ``(organization, product)`` for the opened quantity,
  valued the way ``record_unpriced_receipt_async`` values stock nobody priced:
  at the organization's own average rate over the layers still on hand where
  they agree on its currency, and otherwise at 0.00 marked ``unknown``.

The records are summed as the reconciliation's first pair sums them — not
deleted, with a card and a shelf, a NaN left out — so afterwards all three of
its pairs read zero for the shelves opened here. A shelf that already has a
quant, whatever its batch, is not touched: its drift, if any, is a measured
fact with a history, and restating it here would hide it.

Idempotent by construction: an opened shelf has a quant. One direction only —
afterwards an opening and a quant the bridge wrote are the same row, so
``downgrade`` is a documented no-op (same contract as ``seedfield01``).
"""

import sqlalchemy as sa
from alembic import op

revision = 'openbal01'
down_revision = 'seedfield01'
branch_labels = None
depends_on = None

_OPENING = """
CREATE TEMP TABLE _opening ON COMMIT DROP AS
SELECT i.organization_id, i.template_id, i.storage_location_id,
       SUM(NULLIF(i.quantity, 'NaN'::numeric)) AS quantity
FROM items i
WHERE i.is_deleted IS FALSE
  AND i.template_id IS NOT NULL
  AND i.storage_location_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM stock_quants q
      WHERE q.organization_id = i.organization_id
        AND q.product_template_id = i.template_id
        AND q.storage_location_id = i.storage_location_id
  )
GROUP BY i.organization_id, i.template_id, i.storage_location_id
HAVING SUM(NULLIF(i.quantity, 'NaN'::numeric)) > 0
"""

_QUANTS = """
INSERT INTO stock_quants (
    id, organization_id, product_template_id, storage_location_id,
    quantity, reserved_quantity, removal_strategy, created_at, updated_at
)
SELECT gen_random_uuid(), organization_id, template_id, storage_location_id,
       quantity, 0, 'FIFO', now(), now()
FROM _opening
"""

_MOVES = """
INSERT INTO stock_moves (
    id, organization_id, product_template_id, to_location_id, quantity,
    state, reference_type, created_at, updated_at, completed_at
)
SELECT gen_random_uuid(), organization_id, template_id, storage_location_id,
       quantity, 'done', 'opening_balance', now(), now(), now()
FROM _opening
"""

# The rate ``ValuationService._avco_rate_async`` would answer: the layers still
# on hand, in the organization's own currency (a NULL one counts as it), or
# no rate at all when one of them is in another.
_LAYERS = """
INSERT INTO stock_valuation_layers (
    id, organization_id, product_template_id, quantity, remaining_qty,
    unit_cost, total_value, direction, created_at, currency, cost_basis
)
SELECT gen_random_uuid(), opened.organization_id, opened.template_id,
       opened.quantity, opened.quantity,
       COALESCE(rate.value, 0),
       ROUND(opened.quantity * COALESCE(rate.value, 0), 2),
       'IN', now(), o.currency,
       CASE WHEN rate.value IS NULL THEN 'unknown' ELSE 'average' END
FROM (
    SELECT organization_id, template_id, SUM(quantity) AS quantity
    FROM _opening
    GROUP BY organization_id, template_id
) opened
JOIN organizations o ON o.id = opened.organization_id
LEFT JOIN LATERAL (
    SELECT ROUND(SUM(l.remaining_qty * l.unit_cost) / SUM(l.remaining_qty), 4)
           AS value
    FROM stock_valuation_layers l
    WHERE l.organization_id = opened.organization_id
      AND l.product_template_id = opened.template_id
      AND l.direction = 'IN'
      AND l.remaining_qty > 0
    HAVING bool_and(COALESCE(l.currency, o.currency) IS NOT DISTINCT FROM o.currency)
) rate ON TRUE
"""


def _run_backfill(bind) -> None:
    """Post the opening balance of every shelf the register does not know."""
    bind.execute(sa.text(_OPENING))
    bind.execute(sa.text(_QUANTS))
    bind.execute(sa.text(_MOVES))
    bind.execute(sa.text(_LAYERS))
    bind.execute(sa.text('DROP TABLE _opening'))


def upgrade() -> None:
    _run_backfill(op.get_bind())


def downgrade() -> None:
    """No-op: an opening quant is indistinguishable from any other afterwards."""
