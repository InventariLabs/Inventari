"""Translation logic for the StockMove backfill.

Pure function: takes an ``ItemHistory`` row + its ``Item`` and returns
a ``StockMove`` (or ``None`` to skip).  Lives in ``app.services`` so
it is unit-testable without a DB or CLI.

Translation rules (conservative — skip rather than guess):
  - CREATED + positive quantity  → external receipt
  - MOVED + both from/to + qty    → internal transfer
  - USED + qty                    → external dispatch
  - DISPOSED + qty                → external dispatch
  - QUANTITY_CHANGED + old/new    → direction by sign of delta
  - anything else                 → skip (return None)

Skip reasons logged but not raised — the backfill is a one-time script
that should not abort on a few weird rows.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.stock_move import StockMove, StockMoveState

_QUANTITY_KEYS = ('quantity', 'qty', 'delta', 'amount')


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _extract_quantity(changes: dict | None) -> Decimal | None:
    if not changes:
        return None
    for key in _QUANTITY_KEYS:
        if key in changes:
            qty = _to_decimal(changes[key])
            if qty is not None and qty > 0:
                return qty
    return None


def _extract_from_to(changes: dict) -> tuple[UUID | None, UUID | None]:
    """Pull from/to location UUIDs from a free-form ``changes`` dict.

    Tries several common key spellings.  Returns (None, None) if either
    is missing — caller should skip rather than guess.
    """
    from_loc = (
        changes.get('from_storage_location_id')
        or changes.get('from_location_id')
        or changes.get('from')
    )
    to_loc = (
        changes.get('to_storage_location_id')
        or changes.get('to_location_id')
        or changes.get('to')
    )

    def _coerce(v: Any) -> UUID | None:
        if v is None:
            return None
        try:
            return UUID(str(v))
        except (TypeError, ValueError):
            return None

    return _coerce(from_loc), _coerce(to_loc)


def _make_move(
    *,
    item: Item,
    history: ItemHistory,
    from_location_id: UUID | None,
    to_location_id: UUID | None,
    quantity: Decimal,
) -> StockMove:
    return StockMove(
        id=uuid.uuid4(),  # generate explicitly — backfill uses bulk INSERT, not session.add()
        organization_id=item.organization_id,
        product_template_id=item.template_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        state=StockMoveState.DONE,
        reference_type='item_history',
        reference_id=history.id,
        created_by=history.user_id,
        created_at=history.created_at,
        completed_at=history.created_at,
    )


def translate_history_to_move(
    history: ItemHistory,
    item: Item,
) -> StockMove | None:
    """Translate one ``ItemHistory`` row into a ``StockMove``.

    Returns ``None`` when the row cannot be translated (skipped).  The
    caller logs the skip and continues.
    """
    if item.template_id is None:
        return None

    action = history.action
    changes = history.changes or {}

    if action == 'CREATED':
        qty = _extract_quantity(changes)
        if qty is None or qty <= 0:
            return None
        return _make_move(
            item=item,
            history=history,
            from_location_id=None,
            to_location_id=item.storage_location_id,
            quantity=qty,
        )

    if action == 'MOVED':
        from_loc, to_loc = _extract_from_to(changes)
        if from_loc is None or to_loc is None:
            return None
        qty = _extract_quantity(changes)
        if qty is None or qty <= 0:
            return None
        return _make_move(
            item=item,
            history=history,
            from_location_id=from_loc,
            to_location_id=to_loc,
            quantity=qty,
        )

    if action == 'USED':
        qty = _extract_quantity(changes)
        if qty is None or qty <= 0:
            return None
        return _make_move(
            item=item,
            history=history,
            from_location_id=item.storage_location_id,
            to_location_id=None,
            quantity=qty,
        )

    if action == 'DISPOSED':
        qty = _extract_quantity(changes)
        if qty is None or qty <= 0:
            return None
        return _make_move(
            item=item,
            history=history,
            from_location_id=item.storage_location_id,
            to_location_id=None,
            quantity=qty,
        )

    if action == 'QUANTITY_CHANGED':
        old_qty = _to_decimal(
            changes.get('old_quantity') or changes.get('from_quantity')
        )
        new_qty = _to_decimal(changes.get('new_quantity') or changes.get('to_quantity'))
        if old_qty is None or new_qty is None:
            return None
        delta = new_qty - old_qty
        if delta == 0:
            return None
        if delta > 0:
            return _make_move(
                item=item,
                history=history,
                from_location_id=None,
                to_location_id=item.storage_location_id,
                quantity=delta,
            )
        return _make_move(
            item=item,
            history=history,
            from_location_id=item.storage_location_id,
            to_location_id=None,
            quantity=abs(delta),
        )

    # UPDATED / RESTORED / DELETED / STATUS_CHANGED → no quantity movement.
    return None
