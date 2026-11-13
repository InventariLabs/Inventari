"""Stock reconciliation read-model.

Two pairs are compared, because two pairs can quietly disagree:

- The shelf against the movement ledger. A shelf whose first quant was
  hydrated with its full quantity while the movement recorded only the
  delta carries that gap from its past (ADR-004, superseded by ADR-022).
  Measured so its size is a number, not an assumption.
- The cost layers against the shelf, in quantity. Stock that arrived
  without a price still gets a layer (``average`` or ``unknown``), so a
  gap is stock the two disagree about, not stock nobody priced.

"The shelf" is the records' view (``stock_quants_from_records``). The report
compared two more pairs while there was a quant table — the records against
it, and it against that view — and they ended with the table
(archived ``quantdrop01``): there is one number of stock, and nothing left for it to
disagree with (ADR-022).

A scheduled job (``app.services.reconciliation_job``) runs this on a
cycle and alerts the organization's admins when a measured figure
changes — the endpoint alone answered only when someone thought to ask.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import CTE, Select, and_, func, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ReconciliationDTO
from app.core.money import quantise
from app.models.item import Item
from app.models.stock_ledger_total import StockLedgerTotal
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.stock_valuation_layer import StockValuationLayer

_ZERO = Decimal('0')

#: ``work_mem`` for the report's aggregates (see :func:`get_reconciliation_async`).
_WORK_MEM = '64MB'

# Any difference at all. There used to be a threshold of a thousandth here,
# and the comment beside it said why: both sides were being converted to
# float, so a shelf holding a third of a kilogram three times over showed a
# drift that was not there. Both sides are exact now, and a thousandth is
# the smallest difference these columns can hold — so the threshold that
# hid the noise was also hiding the smallest real drift there is.
_DRIFT_EPSILON = Decimal('0')


async def get_reconciliation_async(
    db: AsyncSession, organization_id: UUID
) -> ReconciliationDTO:
    """The shelf against the movement ledger and against the cost layers.

    ``items_scanned`` counts the live records on a product card — the rows
    the shelf is summed from.

    Both pairs are compared in the database: each side is summed per key,
    the two sums are joined, and one row of ``(count, total)`` comes back.
    The comparison used to run in Python over every group of both sides —
    342 099 shelf groups and 894 478 ledger groups at 100 000 products — so
    the answer took 17–25 s and the memory of the pass grew with the
    organization until a million products ran a worker out of it. Now what
    crosses the wire is the same two numbers whatever the organization's
    size.
    """
    # Both sums have one group per (product, shelf): hundreds of thousands at
    # the sizes this report is sized for. At the default 16 MB each hash
    # aggregate spilled to disk in a score of batches (2.1 s at 100 000
    # products against 1.2 s with the memory); the extra lasts for the
    # transaction and is a ceiling, not a reservation — a larger organization
    # spills beyond it and the memory stays where it was set.
    await db.execute(text(f"SET LOCAL work_mem = '{_WORK_MEM}'"))
    shelf = _shelf_totals(organization_id)
    # One statement for both pairs: the shelf's sums are computed once and
    # read by both, where a statement each computed them twice.
    ledger_pair = _drift_of(
        shelf, _ledger_totals(organization_id), 'template_id', 'location_id'
    ).subquery('ledger_pair')
    layer_pair = _drift_of(
        _shelf_by_template(shelf), _layer_totals(organization_id), 'template_id'
    ).subquery('layer_pair')
    quant_move_count, quant_move_total, layer_quant_count, layer_quant_total = (
        await db.execute(
            select(
                ledger_pair.c.drifted,
                ledger_pair.c.total,
                layer_pair.c.drifted,
                layer_pair.c.total,
            ).select_from(
                # Two one-row aggregates side by side: the product is meant,
                # and said so, or SQLAlchemy warns of a cartesian product.
                ledger_pair.join(layer_pair, true())
            )
        )
    ).one()
    scanned = await db.scalar(
        select(func.count())
        .select_from(Item)
        .where(
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
            Item.template_id.is_not(None),
        )
    )

    return ReconciliationDTO(
        items_scanned=scanned or 0,
        quant_move_drift_count=quant_move_count,
        quant_move_drift_total=quantise(quant_move_total, 3),
        layer_quant_drift_count=layer_quant_count,
        layer_quant_drift_total=quantise(layer_quant_total, 3),
    )


def _shelf_totals(organization_id: UUID) -> CTE:
    """Sum of on-hand quantity per ``(template, location)``, as the records tell it.

    Read from ``stock_quants_from_records``, on a shelf only: the ledger's
    movements arrive at and leave from shelves, and a record on none would
    be a gap no movement could explain. The schema keeps every record on a
    shelf today (``items.storage_location_id`` is NOT NULL).
    """
    view = stock_quants_from_records
    return (
        select(
            view.c.product_template_id.label('template_id'),
            view.c.storage_location_id.label('location_id'),
            func.sum(view.c.quantity).label('total'),
        )
        .where(
            view.c.organization_id == organization_id,
            view.c.storage_location_id.is_not(None),
        )
        .group_by(view.c.product_template_id, view.c.storage_location_id)
        .cte('shelf')
    )


def _drift_of(left: CTE, right: CTE, *keys: str) -> Select:
    """How many keys the two sums disagree on, and by how much in all.

    A key one side lacks counts as zero there. The join is full, so a key
    only the shelf has and a key only the other side has are both drift.
    """
    on = and_(*(left.c[key] == right.c[key] for key in keys))
    delta = func.coalesce(left.c.total, _ZERO) - func.coalesce(right.c.total, _ZERO)
    return (
        select(
            func.count().label('drifted'),
            func.coalesce(func.sum(func.abs(delta)), _ZERO).label('total'),
        )
        .select_from(left.join(right, on, full=True))
        .where(func.abs(delta) > _DRIFT_EPSILON)
    )


def _ledger_totals(organization_id: UUID) -> CTE:
    """What the movement ledger nets to per ``(template, location)``.

    The shelf and the movement ledger can tell different stories. The first
    quant of a product used to be hydrated with its full quantity while its
    movement carried only the delta, so a gap here is expected on a database
    with that past and *measured* rather than presumed — the number to watch
    is one that grows.

    The net stays whole-history on purpose — this pair compares the shelf's
    current state against the ledger's full net, and a time window would
    measure the shelf against nothing. It is read from
    ``stock_ledger_totals``, which the ledger's own triggers keep in the
    statement that writes each movement: this used to add up every done
    movement of the organization on every pass, and the ledger only grows,
    so each pass cost more than the last. Now the pass reads one row per
    product and shelf, however long the history behind them.
    """
    totals = StockLedgerTotal
    return (
        select(
            totals.product_template_id.label('template_id'),
            totals.storage_location_id.label('location_id'),
            totals.quantity.label('total'),
        )
        .where(totals.organization_id == organization_id)
        .cte('ledger')
    )


def _shelf_by_template(shelf: CTE) -> CTE:
    """The shelf summed over its locations, per template."""
    return (
        select(shelf.c.template_id, func.sum(shelf.c.total).label('total'))
        .group_by(shelf.c.template_id)
        .cte('shelf_by_template')
    )


def _layer_totals(organization_id: UUID) -> CTE:
    """What the cost layers still hold, per template.

    Every arrival carries a layer, priced or not: one nobody priced is
    posted at the organization's average rate (``average``) or, with no
    rate to fall back on, at no known cost (``unknown``). So the pair
    against the shelf compares quantities only — a gap is stock the layers
    and the shelf disagree about, not stock without a price, which this
    pair cannot see.
    """
    return (
        select(
            StockValuationLayer.product_template_id.label('template_id'),
            func.sum(StockValuationLayer.remaining_qty).label('total'),
        )
        .where(
            StockValuationLayer.organization_id == organization_id,
            StockValuationLayer.direction == 'IN',
        )
        .group_by(StockValuationLayer.product_template_id)
        .cte('layers')
    )
