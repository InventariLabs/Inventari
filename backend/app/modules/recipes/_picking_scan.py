"""Picking scan orchestrator — coordinates item resolution, FEFO, consume, response.

The sub-steps live in sibling modules to keep this file focused on flow:
  - _picking_item_resolution: barcode/id → ItemDTO + ingredient match
  - _picking_fefo_checks: disambiguation + recommendation
  - _picking_consume: stock decrement + session record
  - _picking_progress: quantity math, completion, response shaping
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from ._picking_consume import (
    consume_for_picking,
    load_or_lock_session_item,
    takes_for_pick,
)
from ._picking_fefo_checks import check_fefo_ambiguity, check_fefo_recommendation
from ._picking_item_resolution import (
    load_recipe_ingredients,
    match_ingredient_or_not_in_recipe,
    resolve_scanned_item_by_barcode,
    resolve_scanned_item_by_id,
)
from ._picking_progress import (
    build_opened_suggestion,
    build_picking_response,
    check_already_picked,
    compute_picking_progress,
    compute_session_completion,
)
from ._picking_session_helpers import _get_session_or_404
from ._picking_uom_bridge import bridge_needed_quantity
from .schemas import PickingScanResponse, UnitMismatch


async def scan_item_in_picking(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    user: Any,
    barcode: str | None,
    item_id: UUID | None,
    from_checklist: bool = False,
) -> PickingScanResponse:
    """Scan a barcode or item_id during an active recipe picking session.

    The flow is:
      1. Load the active session + recipe ingredients.
      2. Resolve the scanned item (by id, or by barcode with template fallback).
      3. Match the item to a recipe ingredient; reject if not in recipe.
      4. Compute the remaining quantity to pick for this ingredient.
      5. Run FEFO checks (disambiguation + recommendation).
      6. Consume the quantity from the item and record session progress.
      7. Build the response (with session-completion + opened-suggestion hints).
    """
    session = await _get_session_or_404(db, session_id, org_id, for_update=True)
    recipe_ingredients = await load_recipe_ingredients(db, session.recipe_id)

    if item_id:
        scanned_item = await resolve_scanned_item_by_id(db, org_id, item_id)
    elif barcode:
        resolved = await resolve_scanned_item_by_barcode(db, org_id, barcode)
        if isinstance(resolved, PickingScanResponse):
            return resolved
        scanned_item = resolved
    else:
        raise ServiceRejectionError('barcode_or_item_id_required')

    matched = match_ingredient_or_not_in_recipe(scanned_item, recipe_ingredients)
    if isinstance(matched, PickingScanResponse):
        return matched
    matched_ingredient = matched

    session_item = await load_or_lock_session_item(
        db, session_id, matched_ingredient.id
    )
    # One read of the unit table for the whole scan: every quantity below is
    # rounded to the step of the unit it is stated in, and the bridge would
    # otherwise load the same rows again.
    uoms_by_id = {
        uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    ingredient_uom = (
        uoms_by_id.get(matched_ingredient.uom_id) if matched_ingredient.uom_id else None
    )
    quantity_to_consume, multiplier, recipe_name = await compute_picking_progress(
        db, session, matched_ingredient, ingredient_uom
    )

    already_picked = check_already_picked(
        matched_ingredient, session_item, quantity_to_consume
    )
    if already_picked:
        return already_picked

    fefo_ambiguity = await check_fefo_ambiguity(
        db, org_id, scanned_item, barcode, item_id, from_checklist
    )
    if fefo_ambiguity:
        return fefo_ambiguity

    fefo_recommendation = await check_fefo_recommendation(
        db, org_id, scanned_item, matched_ingredient, item_id
    )
    if fefo_recommendation:
        return fefo_recommendation

    already_consumed = (
        Decimal(str(session_item.quantity_consumed))
        if session_item and session_item.quantity_consumed
        else Decimal('0')
    )
    remaining_needed = quantity_to_consume - already_consumed

    # The recipe asks in its unit, the shelf is counted in the item's. Picking
    # decrements the item, so the need has to be restated in the item's unit —
    # and when the two measures have no bridge, there is no honest amount to
    # take. Report both readings and leave the stock alone.
    bridge = await bridge_needed_quantity(
        db, org_id, matched_ingredient, scanned_item, remaining_needed, uoms_by_id
    )
    if bridge.needed_in_item_uom is None:
        return PickingScanResponse(
            status='unit_mismatch',
            ingredient_id=matched_ingredient.id,
            ingredient_name=matched_ingredient.name,
            message=get_error_message(
                'picking_unit_mismatch',
                get_current_lang(),
                name=matched_ingredient.name,
            ),
            unit_mismatch=UnitMismatch(
                required_quantity=float(remaining_needed),
                required_uom=bridge.required_uom_symbol,
                available_quantity=float(scanned_item.quantity or 0),
                available_uom=bridge.available_uom_symbol,
            ),
        )

    from ._picking_consume import record_session_item_consumption

    # Usually one record; a pick of a whole bag and a part of another is two.
    progress_total = Decimal('0')
    for source, take in await takes_for_pick(
        db, scanned_item, bridge.needed_in_item_uom, user
    ):
        consume_qty, remaining_qty, consumed_valuation_rate = await consume_for_picking(
            db,
            source,
            take,
            user,
            history_changes={
                'reason': 'recipe_picking',
                'picking_session_id': str(session_id),
                'recipe_name': recipe_name,
                'servings': session.servings,
                'ingredient_name': matched_ingredient.name,
            },
        )
        # What actually left the shelf, restated in the recipe's unit — a
        # partial pick covers the same fraction of the need in either measure.
        progress_qty = core_api.uoms.quantize(
            remaining_needed * consume_qty / bridge.needed_in_item_uom
            if bridge.needed_in_item_uom > 0
            else Decimal('0'),
            # Stated in the recipe's unit, so it is that unit's step that
            # applies — a reading of what was taken, hence the nearest step
            # rather than the next one up.
            bridge.required_uom,
        )
        record_session_item_consumption(
            session_item, source, consume_qty, progress_qty, consumed_valuation_rate
        )
        progress_total += progress_qty
        scanned_item = source

    await db.flush()

    opened_suggestion = await build_opened_suggestion(db, org_id, scanned_item)
    session_complete = await compute_session_completion(
        db, session_id, recipe_ingredients, multiplier, uoms_by_id
    )

    return build_picking_response(
        matched_ingredient,
        session_item,
        progress_total,
        remaining_qty,
        quantity_to_consume,
        session_complete,
        opened_suggestion,
    )
