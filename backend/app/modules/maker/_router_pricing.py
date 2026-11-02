"""Pricing endpoints — compute sale price + persist target margin per template."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException, map_service_errors
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from . import pricing
from ._schemas_pricing import (
    MarginResponse,
    MarginUpdate,
    PricingRequest,
    PricingResponse,
)

router = APIRouter(prefix='/pricing', tags=['maker'])


@router.post(
    '/compute',
    response_model=PricingResponse,
)
@map_service_errors
async def compute_pricing_endpoint(
    data: PricingRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PricingResponse:
    """Stateless pricing compute — does not persist anything."""
    outcome = await pricing.compute_pricing(
        db,
        org_id,
        data.template_id,
        data.produced_qty,
        data.target_margin_pct,
    )
    return PricingResponse(
        template_id=data.template_id,
        produced_qty=data.produced_qty,
        total_cost=outcome.total_cost,
        unit_cost=outcome.unit_cost,
        target_margin_pct=data.target_margin_pct,
        unit_sale_price=outcome.unit_sale_price,
        ingredient_count=outcome.ingredient_count,
        unrated_ingredient_count=outcome.unrated_ingredient_count,
        recipe_state=outcome.recipe_state,
        recipe_id=outcome.recipe_id,
    )


@router.get(
    '/margin/{template_id}',
    response_model=MarginResponse,
)
async def get_margin_endpoint(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> MarginResponse:
    """Read the per-template target margin (default or stored)."""
    template = await core_api.product_templates.get_async(db, org_id, template_id)
    if template is None:
        raise NotFoundException('template', get_current_lang())

    stored = pricing._read_maker_meta(template.meta_data).get('target_margin_pct')
    is_default = stored is None
    value = pricing._coerce_margin(stored, default=pricing.DEFAULT_MARGIN_PCT)
    return MarginResponse(
        template_id=template_id,
        target_margin_pct=value,
        is_default=is_default,
    )


@router.put(
    '/margin/{template_id}',
    response_model=MarginResponse,
)
@map_service_errors
async def set_margin_endpoint(
    template_id: UUID,
    data: MarginUpdate,
    # The margin lands in the product template's own metadata — writing a
    # template is items work, whatever door it came in through.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> MarginResponse:
    """Persist user's preferred target margin for this template."""
    await pricing.set_default_margin_pct(
        db, org_id, template_id, data.target_margin_pct, current_user.id
    )
    return MarginResponse(
        template_id=template_id,
        target_margin_pct=data.target_margin_pct,
        is_default=False,
    )
