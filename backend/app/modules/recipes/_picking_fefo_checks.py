"""Picking FEFO checks — disambiguation and recommendation.

Extracted from _picking_scan.py to keep the orchestrator under the
400-LOC module guideline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._picking_fefo import (
    expiry_of,
    needs_disambiguation,
    open_pack_meets_earlier_sealed,
    select_best_item,
)
from ._picking_session_helpers import (
    _build_disambiguation,
    piece_measure_of_template,
)
from .models import RecipeIngredient
from .schemas import PickingScanResponse

if TYPE_CHECKING:
    from app.core.contracts import ItemDTO


async def check_fefo_ambiguity(
    db: AsyncSession,
    org_id: UUID,
    scanned_item: ItemDTO,
    barcode: str | None,
    item_id: UUID | None,
    from_checklist: bool = False,
) -> PickingScanResponse | None:
    """If a barcode scan resolves to multiple physical locations, return disambiguation.

    A tap on the checklist row sends the recommended record's id, which is not
    a choice: it is asked about an open pack beside an earlier sealed one, but
    not about locations, since the recommendation already names one.
    """
    chosen = bool(item_id) and not from_checklist
    if chosen or not scanned_item.template_id:
        return None
    all_same = await core_api.items.list_by_expiry_async(
        db,
        org_id,
        template_ids=[scanned_item.template_id],
        order='asc',
    )
    today = await core_api.organizations.today_async(db, org_id)
    if (
        needs_disambiguation(all_same) and not from_checklist
    ) or open_pack_meets_earlier_sealed(all_same, today):
        return _build_disambiguation(
            all_same,
            today=today,
            piece_measure=await piece_measure_of_template(
                db, org_id, scanned_item.template_id
            ),
        )
    return None


async def check_fefo_recommendation(
    db: AsyncSession,
    org_id: UUID,
    scanned_item: ItemDTO,
    matched_ingredient: RecipeIngredient,
    item_id: UUID | None,
) -> PickingScanResponse | None:
    """If a different item would be a better FEFO pick, return a fefo_mismatch response.

    The gate is whether the ingredient resolves to stock at all, not whether
    it carries a template_id. Keyed on the link, this warning could never
    fire for an ingredient typed by hand — which is most of them — so a
    picker could take the fresher jar and leave the one about to expire
    without the module saying a word.
    """
    if item_id:
        return None
    from .services import _find_available_items

    items_for_ingredient = await _find_available_items(db, matched_ingredient, org_id)
    if len(items_for_ingredient) <= 1:
        return None
    best, fefo_days_left = select_best_item(
        items_for_ingredient,
        today=await core_api.organizations.today_async(db, org_id),
    )
    if fefo_days_left is None or best.id == scanned_item.id:
        return None
    return PickingScanResponse(
        status='fefo_mismatch',
        ingredient_id=matched_ingredient.id,
        ingredient_name=matched_ingredient.name,
        fefo_mismatch_days_left=fefo_days_left,
        fefo_recommended_item_id=best.id,
        fefo_recommended_expiry_date=str(expiry_of(best)) if expiry_of(best) else None,
        fefo_scanned_item_id=scanned_item.id,
    )
