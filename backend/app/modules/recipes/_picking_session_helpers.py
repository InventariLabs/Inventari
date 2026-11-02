from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemDTO, UomDTO
from app.core.exceptions import NotFoundException
from app.core.open_package import opened_at
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from ._helpers import _location_name
from ._ingredient_matching import match_templates, matching_key
from ._picking_fefo import (
    _should_auto_skip,
    expiry_of,
    fefo_order,
    select_best_item,
)
from .models import PickingSession, RecipeIngredient
from .schemas import (
    DisambiguationCandidate,
    PickingItemSchema,
    PickingScanResponse,
)

# Re-export for use by sub-modules and tests
__all__ = [
    '_get_session_or_404',
    '_ingredient_to_checklist_item',
    '_match_ingredient',
    '_build_disambiguation',
    'piece_measure_of_template',
]


async def _get_session_or_404(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    *,
    for_update: bool = False,
    include_terminal: bool = False,
) -> PickingSession:
    lang = get_current_lang()
    stmt = select(PickingSession).where(
        PickingSession.id == session_id,
        PickingSession.organization_id == org_id,
    )
    if not include_terminal:
        stmt = stmt.where(PickingSession.status == 'active')
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    session = result.scalars().first()
    if not session:
        raise NotFoundException('picking_session', lang)
    return session


async def _ingredient_to_checklist_item(
    ingredient: RecipeIngredient,
    servings_multiplier: float | Decimal,
    db: AsyncSession,
    org_id: UUID,
    uoms_by_id: dict[UUID, UomDTO] | None = None,
) -> PickingItemSchema:
    """Convert a recipe ingredient to a picking checklist item with best-pick suggestion.

    Callers that build a whole checklist pass *uoms_by_id* so the unit table
    is read once for the sheet rather than once per row.
    """
    from .services import _find_available_items

    if uoms_by_id is None:
        uoms_by_id = {
            uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
        }
    ingredient_uom = uoms_by_id.get(ingredient.uom_id) if ingredient.uom_id else None
    # What the sheet asks for is a requirement, so it takes the next step of
    # its unit: a row reading "0.4 pcs" is a row nobody can pick.
    scaled_qty = float(
        core_api.uoms.round_up(
            Decimal(str(ingredient.quantity)) * Decimal(str(servings_multiplier)),
            ingredient_uom,
        )
    )

    recommended_item_id = None
    storage_location = None
    fefo_days_left = None
    fefo_expiry_date = None

    items = await _find_available_items(db, ingredient, org_id)
    if items:
        best, fefo_days_left = select_best_item(
            items, today=await core_api.organizations.today_async(db, org_id)
        )
        recommended_item_id = best.id
        if fefo_days_left is not None and expiry_of(best):
            fefo_expiry_date = str(expiry_of(best))
        storage_location = _location_name(best)

    uom_symbol = None
    if ingredient.uom:
        uom_symbol = ingredient.uom.symbol

    if _should_auto_skip(ingredient, scaled_qty):
        initial_status = 'skipped'
    elif items:
        initial_status = 'pending'
    elif ingredient.template_id or matching_key(ingredient):
        # We know what to look for and it is not there — that is "missing".
        # "unknown" is reserved for an ingredient that names nothing at all,
        # which is the only case a picker genuinely cannot act on.
        initial_status = 'missing'
    else:
        initial_status = 'unknown'

    return PickingItemSchema(
        ingredient_id=ingredient.id,
        name=ingredient.name,
        quantity_to_pick=scaled_qty,
        uom_symbol=uom_symbol,
        recommended_item_id=recommended_item_id,
        location=storage_location,
        fefo_days_left=fefo_days_left,
        fefo_expiry_date=fefo_expiry_date,
        status=initial_status,
        is_linked=ingredient.template_id is not None,
    )


def _match_ingredient(
    item: ItemDTO,
    ingredients: list[RecipeIngredient],
) -> RecipeIngredient | None:
    """Match a scanned item to a recipe ingredient.

    Pass 1 is the ingredient's own template. Pass 2 runs the scanned item's
    name through the same matcher availability uses, so scanning a can of
    "Ciecierzyca w puszce" ticks off "Ciecierzyca z puszki" — the substring
    test it replaces knew neither the inflection nor the preposition, and
    with an empty group name it never fired at all.

    An ingredient the item is actually named after wins over one that
    merely mentions it.
    """
    if item.template_id:
        for ing in ingredients:
            if ing.template_id and ing.template_id == item.template_id:
                return ing

    mentioned: RecipeIngredient | None = None
    for ing in ingredients:
        key = matching_key(ing)
        if not key:
            continue
        matches = match_templates(key, [item])
        if not matches:
            continue
        if matches[0].head_match:
            return ing
        mentioned = mentioned or ing

    return mentioned


async def piece_measure_of_template(
    db: AsyncSession, org_id: UUID, template_id: UUID | None
) -> tuple[float, str] | None:
    """What one piece of the product weighs or holds, with its unit's symbol.

    Weight wins when a card records both. ``None`` for a product whose card
    records neither, which is most of them.
    """
    if template_id is None:
        return None
    template = await core_api.product_templates.get_async(db, org_id, template_id)
    if template is None:
        return None
    for value, uom_id in (
        (template.weight_value, template.weight_uom_id),
        (template.volume_value, template.volume_uom_id),
    ):
        if value and uom_id:
            uom = await core_api.uoms.get_async(db, uom_id, org_id)
            if uom is not None:
                return float(value), uom.symbol
    return None


def _build_disambiguation(
    candidates: list[ItemDTO],
    *,
    today: date,
    piece_measure: tuple[float, str] | None = None,
) -> PickingScanResponse:
    sorted_candidates = fefo_order(candidates, today)
    items_list = []
    for i, c in enumerate(sorted_candidates):
        loc = _location_name(c)
        items_list.append(
            DisambiguationCandidate(
                item_id=c.id,
                quantity=float(c.quantity or 0),
                uom_id=c.uom_id,
                uom_symbol=c.uom_symbol or (c.uom.symbol if c.uom else None),
                piece_measure_value=piece_measure[0] if piece_measure else None,
                piece_measure_symbol=piece_measure[1] if piece_measure else None,
                expiry_date=str(expiry_of(c)) if expiry_of(c) else None,
                location=loc,
                recommended=(i == 0),
                opened=opened_at(c.meta_data) is not None,
                opened_at=opened_at(c.meta_data),
            )
        )
    return PickingScanResponse(
        status='disambiguation_required',
        candidates=items_list,
    )
