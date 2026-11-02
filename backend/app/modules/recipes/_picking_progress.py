"""Picking progress — quantity math, completion check, response shaping.

Extracted from _picking_scan.py to keep the orchestrator under the
400-LOC module guideline.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from ._picking_helpers import check_opened_suggestion
from .models import PickingSession, PickingSessionItem, Recipe, RecipeIngredient
from .schemas import PickingScanResponse

if TYPE_CHECKING:
    from app.core.contracts import ItemDTO, UomDTO


async def compute_picking_progress(
    db: AsyncSession,
    session: PickingSession,
    matched_ingredient: RecipeIngredient,
    ingredient_uom: UomDTO | None = None,
) -> tuple[Decimal, Decimal, str | None]:
    """Return (quantity_to_consume, multiplier, recipe_name) for this ingredient.

    Multiplier scales the ingredient's base quantity to the session's servings.
    quantity_to_consume is the amount needed before subtracting what's already picked.
    The recipe is loaded here anyway, and its name is what makes the item's
    history entry readable without looking anything up.
    """
    recipe_result = await db.execute(
        select(Recipe).where(Recipe.id == session.recipe_id)
    )
    recipe_obj = recipe_result.scalars().first()
    from ._scaling import resolve_multiplier

    multiplier = resolve_multiplier(
        recipe_obj.servings if recipe_obj else 0, session.servings, None
    )
    # A requirement takes the next step of its own unit, not a hard three
    # places: owing 0.4 of a whole-unit ingredient is owing one of them.
    quantity_to_consume = core_api.uoms.round_up(
        Decimal(str(matched_ingredient.quantity)) * multiplier, ingredient_uom
    )
    return quantity_to_consume, multiplier, recipe_obj.name if recipe_obj else None


def check_already_picked(
    matched_ingredient: RecipeIngredient,
    session_item: PickingSessionItem | None,
    quantity_to_consume: Decimal,
) -> PickingScanResponse | None:
    """Return an early-response if this ingredient has already been fully picked."""
    already_consumed = (
        Decimal(str(session_item.quantity_consumed))
        if session_item and session_item.quantity_consumed
        else Decimal('0')
    )
    remaining_needed = quantity_to_consume - already_consumed
    if remaining_needed <= 0:
        return PickingScanResponse(
            status='already_picked',
            ingredient_name=matched_ingredient.name,
            message=get_error_message(
                'picking_already_picked', name=matched_ingredient.name
            ),
        )
    return None


async def compute_session_completion(
    db: AsyncSession,
    session_id: UUID,
    recipe_ingredients: list[RecipeIngredient],
    multiplier: Decimal,
    uoms_by_id: dict[UUID, UomDTO] | None = None,
) -> bool:
    """Return True if every ingredient has been picked (or explicitly skipped/missing)."""
    result = await db.execute(
        select(PickingSessionItem).where(PickingSessionItem.session_id == session_id)
    )
    all_session_items = list(result.scalars().all())
    if not all_session_items:
        return False
    ing_map = {ing.id: ing for ing in recipe_ingredients}
    for si in all_session_items:
        if si.status not in ('picked', 'skipped', 'missing'):
            return False
        if si.status != 'picked':
            continue
        ing = ing_map.get(si.ingredient_id) if si.ingredient_id else None
        if not ing:
            continue
        ing_uom = (uoms_by_id or {}).get(ing.uom_id) if ing.uom_id else None
        # Same rounding as the requirement the session was started with —
        # a different one here would leave a session one step short forever.
        needed = core_api.uoms.round_up(
            Decimal(str(ing.quantity)) * multiplier, ing_uom
        )
        consumed = Decimal(str(si.quantity_consumed or 0))
        if consumed < needed:
            return False
    return True


async def build_opened_suggestion(
    db: AsyncSession, org_id: UUID, scanned_item: ItemDTO
) -> Any:
    """Return the next opened-product suggestion after this pick, or None."""
    if not scanned_item.template_id:
        return None
    all_same_tmpl = await core_api.items.list_by_expiry_async(
        db,
        org_id,
        template_ids=[scanned_item.template_id],
        order='asc',
    )
    template = await core_api.product_templates.get_with_uom_async(
        db, org_id, scanned_item.template_id
    )

    return check_opened_suggestion(scanned_item, all_same_tmpl, template)


def build_picking_response(
    matched_ingredient: RecipeIngredient,
    session_item: PickingSessionItem | None,
    consume_qty: Decimal,
    remaining_qty: float,
    quantity_to_consume: Decimal,
    session_complete: bool,
    opened_suggestion: Any,
) -> PickingScanResponse:
    """Compose the final PickingScanResponse for a successful pick."""
    uom_symbol = matched_ingredient.uom.symbol if matched_ingredient.uom else None
    new_accumulated = (
        Decimal(str(session_item.quantity_consumed or 0))
        if session_item
        else consume_qty
    )
    ingredient_remaining = max(Decimal('0'), quantity_to_consume - new_accumulated)
    return PickingScanResponse(
        status='picked',
        ingredient_id=matched_ingredient.id,
        ingredient_name=matched_ingredient.name,
        quantity_consumed=float(consume_qty),
        uom_symbol=uom_symbol,
        item_remaining_quantity=remaining_qty,
        ingredient_remaining_quantity=(
            float(ingredient_remaining) if ingredient_remaining > 0 else None
        ),
        session_complete=session_complete,
        message=get_error_message(
            'picking_picked',
            get_current_lang(),
            name=matched_ingredient.name,
            quantity=f'{consume_qty} {uom_symbol}' if uom_symbol else str(consume_qty),
        ),
        opened_suggestion=opened_suggestion,
    )
