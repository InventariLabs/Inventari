from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import catalogue_refusal
from app.core.module_sdk import PaginatedResponse

from .schemas import MyAssetHistoryItem, MyAssetItem

router = APIRouter()


@router.get('/my-assets', response_model=PaginatedResponse[MyAssetItem])
async def get_my_assets(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .my_assets_service import get_my_active_assets

    if not current_user.email:
        raise catalogue_refusal('user_email_required')
    assets = await get_my_active_assets(db, org_id, current_user.email)
    return PaginatedResponse.from_full_list(assets, offset=offset, limit=limit)


@router.get('/my-assets/history', response_model=PaginatedResponse[MyAssetHistoryItem])
async def get_my_assets_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .my_assets_service import get_my_assignment_history

    if not current_user.email:
        raise catalogue_refusal('user_email_required')
    rows, total = await get_my_assignment_history(
        db, org_id, current_user.email, limit=limit, offset=offset
    )
    return PaginatedResponse.from_slice(rows, offset=offset, limit=limit, total=total)
