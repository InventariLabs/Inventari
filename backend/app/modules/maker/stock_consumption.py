"""Cross-location stock consumption for the maker module.

A production run asks for an ingredient, not for an ingredient on a
particular shelf, so it draws on every location the organization has.
That draw lives in Core — ``core_api.stock.take_from_the_records_async``
with no shelf named — beside the single-shelf one it shares its removal
order with.

It used to live here, with a Python re-implementation of Core's FEFO/FIFO
sort and a comment naming the line numbers it mirrored. The mirror is gone;
what is left is the module's own vocabulary for the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api


@dataclass(frozen=True)
class ConsumptionRecord:
    """What a consumption took off one grain: a batch, on a shelf, of an owner."""

    storage_location_id: UUID
    lot_id: UUID | None
    consumed_qty: Decimal
    owner_id: UUID | None = None


async def consume_across_locations(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    quantity: Decimal,
    *,
    child_template: object | None = None,
    history_changes: dict[str, Any] | None = None,
    user_id: UUID,
    reference_id: UUID,
    location_id: UUID | None = None,
) -> list[ConsumptionRecord]:
    """Consume ``quantity`` of a template from available stock.

    ``location_id`` is the set the caller's availability check judged the
    draw under: None draws on every location the organization has (the
    GLOBAL scope — the behaviour this function was born with), a location
    narrows the draw to that shelf, so the run eats exactly the stock it
    was checked against and not a batch the check never saw.

    Order and refusal are Core's: FEFO by earliest expiry or use-by date,
    FIFO by age otherwise, and a ``ValueError`` before anything is
    decremented when the whole request cannot be met — a run that failed on
    its fourth ingredient would otherwise have taken three off the books.

    Consignment stock counts. A run consumes what is physically on the
    shelf, and whose goods they are is a question for the settlement, not
    for the mixer.

    The draw is planned from the records and names them, and Core writes
    the records it named down — *history_changes* and *user_id* go with that
    write, so the item's history says which run ate the stock instead of
    reading a bare quantity change — and the movements off each shelf, one
    per shelf and batch, naming the run (*reference_id*). Naming the record
    is what let the mirror go: it summed the draw per shelf and reached for
    the shelf's records, so two records of one batch left the run wrong
    about which of them it ate.
    """
    # The carrier in hand is usually a DTO that does not carry the strategy;
    # asking Core to resolve it here would send the default down as an
    # override and beat the template's own FEFO. Name a strategy only when
    # the carrier actually has one — with none named, Core reads the
    # template itself.
    return [
        ConsumptionRecord(
            storage_location_id=cast(UUID, taken.location_id),
            lot_id=taken.lot_id,
            consumed_qty=taken.consumed,
            owner_id=taken.owner_id,
        )
        for taken in await core_api.stock.take_from_the_records_async(
            db,
            organization_id,
            product_template_id,
            location_id,
            quantity,
            removal_strategy=getattr(child_template, 'removal_strategy', None),
            any_owner=True,
            history_changes=history_changes,
            user_id=user_id,
            reference_type='maker_production',
            reference_id=reference_id,
        )
    ]


# architecture: allow_direct_db_access
# reason: CoreAPI stock.list_quants_async accepts one template per call; batched GROUP BY over the records view avoids catalog N+1
async def get_stock_totals(
    db: AsyncSession,
    organization_id: UUID,
    template_ids: list[UUID],
) -> dict[UUID, Decimal]:
    """Total on-hand quantity per product template, batched (no N+1).

    The total is what the records say, summed by the
    ``stock_quants_from_records`` view. Returns only templates with a
    positive stock total, mirroring the previous per-template
    ``core_api.stock.list_quants_async`` loop.
    """
    from app.models.stock_quants_from_records import stock_quants_from_records

    view = stock_quants_from_records
    if not template_ids:
        return {}
    result = await db.execute(
        select(
            view.c.product_template_id,
            func.coalesce(func.sum(view.c.quantity), Decimal('0')),
        )
        .where(
            view.c.organization_id == organization_id,
            view.c.product_template_id.in_(template_ids),
        )
        .group_by(view.c.product_template_id)
    )
    totals: dict[UUID, Decimal] = {}
    for template_id, total in result.all():
        if total is not None and total > 0:
            totals[template_id] = total
    return totals
