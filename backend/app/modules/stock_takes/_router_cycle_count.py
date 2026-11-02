from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import NotFoundException, catalogue_refusal
from app.core.module_sdk import PaginatedResponse

from .cycle_count_service import (
    create_schedule as cc_create_schedule,
)
from .cycle_count_service import (
    delete_schedule as cc_delete_schedule,
)
from .cycle_count_service import (
    generate_cycle_count as cc_generate_cycle_count,
)
from .cycle_count_service import (
    get_schedule as cc_get_schedule,
)
from .cycle_count_service import (
    list_schedules as cc_list_schedules,
)
from .cycle_count_service import (
    update_schedule as cc_update_schedule,
)
from .models import CycleCountSchedule, StockTake
from .schemas import (
    CycleCountScheduleCreate,
    CycleCountScheduleResponse,
    CycleCountScheduleUpdate,
    StockTakeResponse,
)

router = APIRouter()


@router.post(
    '/cycle-count-schedules',
    response_model=CycleCountScheduleResponse,
    status_code=201,
)
async def create_cycle_count_schedule(
    data: CycleCountScheduleCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> CycleCountSchedule:
    org_id = require_org(current_user)
    scope_filter = data.scope_filter
    if not scope_filter and data.location_id:
        scope_filter = {'storage_location_id': str(data.location_id)}
    schedule = await cc_create_schedule(
        db,
        org_id,
        current_user.id,
        name=data.name,
        frequency=data.frequency,
        scope=data.scope,
        scope_filter=scope_filter,
        sample_size=data.sample_size,
        tolerance_percent=data.tolerance_percent,
    )
    return schedule


@router.get(
    '/cycle-count-schedules',
    response_model=PaginatedResponse[CycleCountScheduleResponse],
)
async def list_cycle_count_schedules(
    active_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    schedules = await cc_list_schedules(db, org_id, active_only=active_only)
    return PaginatedResponse.from_full_list(schedules, offset=offset, limit=limit)


@router.get(
    '/cycle-count-schedules/{schedule_id}',
    response_model=CycleCountScheduleResponse,
)
async def get_cycle_count_schedule(
    schedule_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> CycleCountSchedule:
    org_id = require_org(current_user)
    schedule = await cc_get_schedule(db, schedule_id, org_id)
    if not schedule:
        raise NotFoundException('cycle_count_schedule')
    return schedule


# The pair this writer's journal keys come from: the endpoint hands the
# service the update payload's key set, so every field the schedule's journal
# can name is a field the schema and the model share. The snapshot-key
# exporter reads this declaration (backend/scripts/export_audit_snapshot_keys.py).
AUDIT_PAYLOAD_SCHEMA = ('CycleCountScheduleUpdate', 'CycleCountSchedule')


@router.patch(
    '/cycle-count-schedules/{schedule_id}',
    response_model=CycleCountScheduleResponse,
)
async def update_cycle_count_schedule(
    schedule_id: UUID,
    data: CycleCountScheduleUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> CycleCountSchedule:
    org_id = require_org(current_user)
    updates = data.model_dump(exclude_unset=True)
    # Clearable is not the same as optional: scope_filter, sample_size and
    # tolerance_percent back nullable columns, so a named null clears them;
    # the other fields of the schema back NOT NULL columns and a null
    # naming one is refused here rather than silently dropped.
    not_clearable = {'name', 'frequency', 'scope', 'is_active'} & set(updates)
    clear_attempts = sorted(name for name in not_clearable if updates[name] is None)
    if clear_attempts:
        raise catalogue_refusal(
            'field_cannot_be_cleared', fields=', '.join(clear_attempts)
        )
    return await cc_update_schedule(
        db, schedule_id, org_id, user_id=current_user.id, **updates
    )


@router.delete('/cycle-count-schedules/{schedule_id}', status_code=204)
async def delete_cycle_count_schedule(
    schedule_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    if not await cc_delete_schedule(db, schedule_id, org_id, user_id=current_user.id):
        raise NotFoundException('cycle_count_schedule')


@router.post(
    '/cycle-count-schedules/{schedule_id}/run',
    response_model=StockTakeResponse,
    status_code=201,
)
async def run_cycle_count(
    schedule_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTake:
    org_id = require_org(current_user)
    stock_take = await cc_generate_cycle_count(db, schedule_id, org_id, current_user.id)
    return stock_take
