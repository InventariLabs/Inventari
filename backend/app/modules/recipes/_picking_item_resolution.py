"""Picking item resolution — resolve a scanned barcode/item_id to an ItemDTO.

Extracted from _picking_scan.py to keep the orchestrator under the
400-LOC module guideline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from ._picking_consume import lock_record_for_pick
from ._picking_fefo import (
    needs_disambiguation,
    open_pack_meets_earlier_sealed,
    select_best_item,
)
from ._picking_session_helpers import (
    _build_disambiguation,
    _match_ingredient,
    piece_measure_of_template,
)
from .models import RecipeIngredient
from .schemas import PickingScanResponse

if TYPE_CHECKING:
    from app.core.contracts import ItemDTO


async def load_recipe_ingredients(
    db: AsyncSession, recipe_id: UUID
) -> list[RecipeIngredient]:
    """Load all RecipeIngredient rows for the given recipe."""
    result = await db.execute(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
    )
    return list(result.scalars().all())


async def resolve_scanned_item_by_id(
    db: AsyncSession, org_id: UUID, item_id: UUID
) -> ItemDTO:
    """Fetch and lock the item by primary key, raising 404 if not found."""
    item = await lock_record_for_pick(db, org_id, item_id)
    if not item:
        raise NotFoundException('item', get_current_lang())
    return item


async def resolve_scanned_item_by_barcode(
    db: AsyncSession, org_id: UUID, barcode: str
) -> ItemDTO | PickingScanResponse:
    """Resolve a scanned barcode to an Item, or to an early-return response.

    Returns:
        - ItemDTO when one is unambiguously resolvable.
        - PickingScanResponse when the caller should return it directly
          (product not recognized, not in stock, or disambiguation needed).
    """
    found = await core_api.items.find_by_barcode_async(db, org_id, barcode)
    if found:
        item = await lock_record_for_pick(db, org_id, found.id)
        # A record emptied while its lock was waited for no longer answers to
        # the barcode.
        if item and item.quantity and item.quantity > 0:
            return item

    template = await core_api.product_templates.lookup_by_barcode_async(
        db, org_id, barcode
    )
    if not template:
        return PickingScanResponse(
            status='not_in_recipe',
            message='Product not recognized',
        )

    candidates = await core_api.items.list_by_expiry_async(
        db,
        org_id,
        template_ids=[template.id],
        order='asc',
    )
    if not candidates:
        return not_in_stock_response()
    today = await core_api.organizations.today_async(db, org_id)
    if needs_disambiguation(candidates) or open_pack_meets_earlier_sealed(
        candidates, today
    ):
        return _build_disambiguation(
            candidates,
            today=today,
            piece_measure=await piece_measure_of_template(db, org_id, template.id),
        )
    best, _ = select_best_item(candidates, today=today)
    item = await lock_record_for_pick(db, org_id, best.id)
    if not item:
        return PickingScanResponse(
            status='not_in_recipe',
            message='Product not recognized',
        )
    if not item.quantity:
        # Emptied while its lock was waited for. The product's stock is locked
        # now, so reading again chooses among what is left.
        return await resolve_scanned_item_by_barcode(db, org_id, barcode)
    return item


def not_in_stock_response(
    ingredient: RecipeIngredient | None = None,
) -> PickingScanResponse:
    """Nothing left to take, so nothing is picked."""
    return PickingScanResponse(
        status='not_in_stock',
        ingredient_id=ingredient.id if ingredient else None,
        ingredient_name=ingredient.name if ingredient else None,
        message='Product not in stock',
    )


def match_ingredient_or_not_in_recipe(
    scanned_item: ItemDTO, recipe_ingredients: list[RecipeIngredient]
) -> RecipeIngredient | PickingScanResponse:
    """Match the scanned item to a recipe ingredient, or return the not-in-recipe response."""
    matched = _match_ingredient(scanned_item, recipe_ingredients)
    if not matched:
        return PickingScanResponse(
            status='not_in_recipe',
            message='This product is not an ingredient of this recipe',
        )
    return matched
