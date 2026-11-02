from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.module_sdk import PaginatedResponse

from .schemas import (
    MaintenanceLogCreate,
    MaintenanceLogSchema,
    MaintenanceLogUpdate,
)
from .services import (
    count_item_logs,
    create_log,
    delete_log,
    get_item_logs,
    update_log,
)

router = APIRouter()


@router.post('/maintenance', response_model=MaintenanceLogSchema, status_code=201)
async def add_maintenance_log(
    data: MaintenanceLogCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await create_log(db, org_id, data, current_user.id)


@router.get(
    '/maintenance/item/{item_id}',
    response_model=PaginatedResponse[MaintenanceLogSchema],
)
async def item_maintenance_history(
    item_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    rows = await get_item_logs(db, org_id, item_id, limit=limit, offset=offset)
    total = await count_item_logs(db, org_id, item_id)
    return PaginatedResponse.from_slice(rows, offset=offset, limit=limit, total=total)


@router.put('/maintenance/{log_id}', response_model=MaintenanceLogSchema)
async def edit_maintenance_log(
    log_id: UUID,
    data: MaintenanceLogUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await update_log(db, org_id, log_id, data, current_user.id)


@router.delete('/maintenance/{log_id}', status_code=204)
async def remove_maintenance_log(
    log_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> None:
    await delete_log(db, org_id, log_id, current_user.id)
