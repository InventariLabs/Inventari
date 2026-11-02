from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.module_sdk import PaginatedResponse

from .dashboard_service import (
    get_dashboard,
    get_warranty_alerts,
    warranty_horizon_days,
)
from .schemas import EquipmentDashboard, WarrantyAlert

router = APIRouter()


@router.get('/dashboard', response_model=EquipmentDashboard)
async def equipment_dashboard(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await get_dashboard(db, org_id)


@router.get('/warranty-alerts', response_model=PaginatedResponse[WarrantyAlert])
async def warranty_alerts(
    days: int | None = Query(
        None,
        ge=1,
        le=365,
        description="How far ahead to look; by default the module's own setting",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    if days is None:
        days = await warranty_horizon_days(db, org_id)
    alerts = await get_warranty_alerts(db, org_id, days=days)
    return PaginatedResponse.from_full_list(alerts, offset=offset, limit=limit)
