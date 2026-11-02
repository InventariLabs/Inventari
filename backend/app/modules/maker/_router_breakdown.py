"""Cost breakdown endpoint — read-only cost resolution for a BOM at qty."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org

from . import cost_breakdown
from ._schemas_breakdown import CostBreakdownResponse

router = APIRouter(prefix='/breakdown', tags=['maker'])


@router.get(
    '/{template_id}',
    response_model=CostBreakdownResponse,
)
async def get_cost_breakdown(
    template_id: UUID,
    qty: Decimal = Query(..., gt=0),
    recipe_id: UUID | None = Query(
        None,
        description='Formula to resolve; omit for the default one',
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> CostBreakdownResponse:
    return await cost_breakdown.compute_breakdown(
        db, org_id, template_id, qty, recipe_id=recipe_id
    )
