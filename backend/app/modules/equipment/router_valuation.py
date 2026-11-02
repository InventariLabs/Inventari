from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    NotFoundException,
)

from .schemas import (
    AssetValuation,
    FleetValuation,
)

router = APIRouter()


@router.get('/valuation', response_model=FleetValuation)
async def fleet_valuation(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    from .depreciation_service import get_fleet_valuation_async

    return await get_fleet_valuation_async(db, org_id)


@router.get('/{item_id}/valuation', response_model=AssetValuation)
async def asset_valuation(
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    from .depreciation_service import get_asset_valuation_async

    result = await get_asset_valuation_async(db, org_id, item_id)
    if not result:
        raise NotFoundException(resource='item') from None
    return result
