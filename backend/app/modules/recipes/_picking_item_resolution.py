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
    """Fetch the item by primary key, raising 404 if not found."""
    lang = get_current_lang()
    dto = await core_api.items.get_for_update_async(db, org_id, item_id)
    if not dto:
        raise NotFoundException('item', lang)
    item = await core_api.items.get_async(db, org_id, dto.id)
    assert item is not None
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
    dto = await core_api.items.find_by_barcode_async(
        db, org_id, barcode, for_update=True
    )
    if dto:
        item = await core_api.items.get_async(db, org_id, dto.id)
        assert item is not None
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
        return PickingScanResponse(
            status='not_in_recipe',
            message='Product not in stock',
        )
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
    resolved = await core_api.items.get_for_update_async(db, org_id, best.id)
    if not resolved:
        return PickingScanResponse(
            status='not_in_recipe',
            message='Product not recognized',
        )
    item = await core_api.items.get_async(db, org_id, resolved.id)
    assert item is not None
    return item


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
