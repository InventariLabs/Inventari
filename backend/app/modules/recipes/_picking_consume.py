"""Picking consume — the write side: lock, decrement stock, record session.

Extracted from _picking_scan.py to keep the orchestrator under the
400-LOC module guideline.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemAction
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._picking_fefo import _resolve_user_id
from .models import PickingSessionItem

if TYPE_CHECKING:
    from app.core.contracts import ItemDTO

#: The ledger's name for a movement cooking caused, taken or put back.
PICKING_MOVE_REFERENCE_TYPE = 'recipe_picking'


def picking_move_reference(history_changes: dict[str, Any] | None) -> dict[str, Any]:
    """The ledger reference for a pick, read off the history it already writes.

    Without it the movement is filed under the record it changed, and the
    moves register shows cooking as "by hand" — a put-back even reads as a
    delivery from outside. The session is the thing that caused it.
    """
    session_id = (history_changes or {}).get('picking_session_id')
    if not session_id:
        return {}
    return {
        'move_reference_type': PICKING_MOVE_REFERENCE_TYPE,
        'move_reference_id': UUID(str(session_id)),
    }


async def load_or_lock_session_item(
    db: AsyncSession, session_id: UUID, ingredient_id: UUID
) -> PickingSessionItem | None:
    """Fetch the existing PickingSessionItem for this ingredient, locked for update."""
    result = await db.execute(
        select(PickingSessionItem)
        .where(
            PickingSessionItem.session_id == session_id,
            PickingSessionItem.ingredient_id == ingredient_id,
        )
        .with_for_update()
    )
    return result.scalars().first()


async def takes_for_pick(
    db: AsyncSession, scanned_item: ItemDTO, needed: Decimal, user: Any
) -> list[tuple[ItemDTO, Decimal]]:
    """The records a pick is taken from, and how much from each, in order.

    Cooking 200 g out of a 2 kg bag opens that bag, the way Use partially
    does, so the stock records when it was opened and the sealed bags beside
    it stay sealed. Taking 1.25 bags takes one whole bag and opens another for
    the quarter. A pick of whole units only opens nothing.
    """
    taken = min(needed, Decimal(str(scanned_item.quantity)))
    whole = taken.to_integral_value(rounding=ROUND_FLOOR)
    if taken == whole:
        return [(scanned_item, needed)]
    opened = await core_api.items.open_to_take_part_async(
        db,
        scanned_item.organization_id,
        scanned_item.id,
        user_id=_resolve_user_id(user),
    )
    if opened is None or opened.id == scanned_item.id:
        return [(scanned_item, needed)]
    open_record = (
        await core_api.items.get_async(db, scanned_item.organization_id, opened.id)
        or scanned_item
    )
    if whole == 0:
        return [(open_record, needed)]
    # The sealed record lost the unit that was split off: read it again.
    sealed = await core_api.items.get_async(
        db, scanned_item.organization_id, scanned_item.id
    )
    return [(sealed or scanned_item, whole), (open_record, needed - whole)]


async def consume_for_picking(
    db: AsyncSession,
    scanned_item: ItemDTO,
    remaining_needed: Decimal,
    user: Any,
    history_changes: dict[str, Any] | None = None,
) -> tuple[Decimal, Decimal, Decimal | None]:
    """Decrement the item's quantity and record consumption.

    ``history_changes`` says why the stock left, in the same place a stock take
    says it (``reason`` plus the id of what caused it). In a household profile
    there is no warehouse module and no organization journal to ask, so the item
    history is the only account of the ubytek there will ever be, and
    ``{'old': 500.0, 'new': 499.0}`` is not an account of anything.

    Returns (consume_qty, remaining_qty, consumed_valuation_rate).
    """
    # Inventory period lock — picking is a real-time stock mutation, and
    # which day it is decides whether it passes, so it is the
    # organization's day rather than the server's.
    await core_api.periods.check_not_closed_async(
        db,
        scanned_item.organization_id,
        await core_api.organizations.today_async(db, scanned_item.organization_id),
    )

    available = Decimal(str(scanned_item.quantity))
    consume_qty = min(remaining_needed, available)
    new_quantity = max(Decimal('0'), available - consume_qty)
    updated_item = await core_api.items.update_quantity_async(
        db,
        scanned_item.organization_id,
        scanned_item.id,
        new_quantity,
        user_id=_resolve_user_id(user),
        history_changes=history_changes,
        sync_valuation=False,
        **picking_move_reference(history_changes),
    )
    if updated_item is None:
        raise ServiceRejectionError('item_not_found')

    consumed_valuation_rate = None
    if scanned_item.template_id:
        consumed_valuation_rate = await core_api.valuation.get_current_rate_async(
            db, scanned_item.organization_id, scanned_item.template_id
        )
        # Cooking uses stock up. The ledger records it as such so the
        # consumption report counts a picked ingredient the same way it
        # counts one taken off the shelf by hand.
        await core_api.valuation.record_delivery_async(
            db,
            scanned_item.organization_id,
            scanned_item.template_id,
            consume_qty,
            reason=ItemAction.USED.value,
            item_id=scanned_item.id,
        )
    # What is left is the number just written, not a float subtraction of it:
    # 0.3 less 0.1 in floats is 0.19999999999999998 of a shelf.
    return consume_qty, new_quantity, consumed_valuation_rate


def record_session_item_consumption(
    session_item: PickingSessionItem | None,
    scanned_item: ItemDTO,
    consume_qty: Decimal,
    progress_qty: Decimal,
    consumed_valuation_rate: Decimal | None,
) -> None:
    """Append this scan to the PickingSessionItem breakdown and mark it picked.

    Two quantities, two units, on purpose. ``consume_qty`` is what left this
    item and is stored in the item's own unit, because undo restores it to
    that item. ``progress_qty`` is the same pick expressed in the recipe's
    unit, because that is what the checklist counts down.
    """
    if not session_item:
        return
    session_item.item_id = scanned_item.id
    session_item.quantity_consumed = (
        session_item.quantity_consumed or Decimal('0')
    ) + progress_qty
    session_item.status = 'picked'
    if (
        consumed_valuation_rate is not None
        and session_item.consumed_valuation_rate is None
    ):
        session_item.consumed_valuation_rate = consumed_valuation_rate
    breakdown = list(session_item.picked_items or [])
    breakdown.append({'item_id': str(scanned_item.id), 'quantity': str(consume_qty)})
    session_item.picked_items = breakdown
