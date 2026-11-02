"""What the stock that left was worth, read from the ledger.

The consumption and waste reports used to take this figure out of
``ItemHistory.changes`` under the keys ``wasted_cost``, ``consumed_cost``,
``quantity_consumed`` and ``quantity_discarded``. Nothing in the application
writes those keys — the consume and discard path records ``{qty, old, reason,
notes}`` — so the value of waste, the waste percentage and the per-product
consumption were silent zeros in every organization. The keys existed only in
the tests, which seeded the shape production never creates: that is why the
defect survived a green suite for so long.

The value now comes from where an ERP keeps it. Every outflow posts a
``StockValuationLayer`` with ``direction='OUT'``, priced at the rate in force
at that moment and never recomputed, so a report about March says the same
thing in December.

Two consequences worth stating plainly, because they are the price of a
figure that does not move:

* Outflows recorded before the ledger's outgoing half existed have no layer.
  They are unknown, not zero — see ``window_is_valued_async``.
* A record with no product template has no layer either, since valuation is
  kept per template. Its quantity still counts; its value cannot.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_ownership import general_rows
from app.models.item import Item
from app.models.item_history import (
    CONSUMPTION_ACTIONS,
    DISPOSAL_ACTIONS,
    ItemHistory,
)
from app.models.stock_valuation_layer import StockValuationLayer


async def outflow_value_by_item_async(
    db: AsyncSession,
    organization_id: UUID,
    date_from: datetime,
    reasons: tuple[str, ...],
    hidden_tags: set[str] | None = None,
) -> dict[UUID, Decimal]:
    """``{item_id: value}`` for outflows since *date_from* with these reasons.

    Keyed by the record the stock left rather than by its product template,
    so a report can name a product without apportioning one template's value
    across the several records that share it.

    Exact all the way. The sum comes out of the ledger as a ``Decimal`` and
    used to be cast to ``float`` here, at the first step — so every total
    built on top of it was accumulated in binary and rounded by a rule
    nothing else in the application uses. It becomes a float once, at the
    edge where the report is built.

    *hidden_tags* leaves out the records a vertical module claims, for a
    report that sums the whole answer rather than the records it lists.
    """
    module_records = (
        StockValuationLayer.item_id.not_in(
            select(Item.id).where(
                Item.organization_id == organization_id, ~general_rows(hidden_tags)
            )
        )
        if hidden_tags
        else true()
    )
    rows = await db.execute(
        select(
            StockValuationLayer.item_id,
            func.sum(StockValuationLayer.total_value),
        )
        .where(
            StockValuationLayer.organization_id == organization_id,
            StockValuationLayer.direction == 'OUT',
            StockValuationLayer.reason.in_(reasons),
            StockValuationLayer.item_id.is_not(None),
            StockValuationLayer.created_at >= date_from,
            module_records,
        )
        .group_by(StockValuationLayer.item_id)
    )
    return {
        item_id: total or Decimal('0')
        for item_id, total in rows.all()
        if item_id is not None
    }


async def consumed_value_by_item_async(
    db: AsyncSession, organization_id: UUID, date_from: datetime
) -> dict[UUID, Decimal]:
    """Value of stock used up, per record."""
    return await outflow_value_by_item_async(
        db, organization_id, date_from, CONSUMPTION_ACTIONS
    )


async def wasted_value_by_item_async(
    db: AsyncSession,
    organization_id: UUID,
    date_from: datetime,
    hidden_tags: set[str] | None = None,
) -> dict[UUID, Decimal]:
    """Value of stock thrown away, per record."""
    return await outflow_value_by_item_async(
        db, organization_id, date_from, DISPOSAL_ACTIONS, hidden_tags
    )


async def window_is_valued_async(
    db: AsyncSession, organization_id: UUID, date_from: datetime
) -> bool:
    """Whether every outflow in this window has a price beside it.

    "Nothing was thrown away" and "we were not counting yet" are different
    answers, and an empty sum returns the same figure for both. A report that
    cannot tell them apart prints a confident 0.00 over a month of waste,
    which is the defect this module exists to end.

    They are told apart by looking, not by a configured cut-over date: an
    outflow whose record has a product template but no outgoing layer is one
    this ledger never priced — it happened before the outgoing half existed,
    or its product has no cost basis at all. Either way the total would be
    short by an unknown amount, so there is no total.

    Records with no template are left out of the question entirely: valuation
    is kept per template, so those were never going to be priced and their
    absence says nothing about the ledger.
    """
    outflow_items = set(
        (
            await db.scalars(
                # Distinct records, not every event: the question is asked
                # per record, and the window may hold thousands of events.
                select(ItemHistory.item_id)
                .distinct()
                .join(Item, ItemHistory.item_id == Item.id)
                .where(
                    ItemHistory.organization_id == organization_id,
                    Item.organization_id == organization_id,
                    Item.template_id.is_not(None),
                    ItemHistory.action.in_(CONSUMPTION_ACTIONS + DISPOSAL_ACTIONS),
                    ItemHistory.created_at >= date_from,
                )
            )
        ).all()
    )
    if not outflow_items:
        # Nothing left the shelves, which is a fact, not a gap.
        return True

    priced = set(
        (
            await db.scalars(
                select(StockValuationLayer.item_id).where(
                    StockValuationLayer.organization_id == organization_id,
                    StockValuationLayer.direction == 'OUT',
                    StockValuationLayer.item_id.in_(outflow_items),
                    StockValuationLayer.created_at >= date_from,
                    # An outflow the layers could not cover posts a layer too,
                    # so that the move is in the books at all — but its value
                    # is not known, and counting it as priced would put a
                    # confident total over a figure that is short. So is one
                    # that drained stock nobody priced.
                    StockValuationLayer.carries_a_cost,
                )
            )
        ).all()
    )
    return not (outflow_items - priced)
