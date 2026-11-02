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
from app.core.exceptions import ConflictException
from app.core.module_sdk import PaginatedResponse

from ._overdue_service import list_overdue_assignments
from .schemas import (
    AssignmentCheckin,
    AssignmentCreate,
    AssignmentListResponse,
    AssignmentSchema,
    OverdueAssignmentListResponse,
)
from .services import (
    checkin,
    checkout,
    count_item_assignment_history,
    get_item_assignment_history,
    list_active_assignments,
)

router = APIRouter()


@router.post('/assignments', response_model=AssignmentSchema, status_code=201)
async def checkout_asset(
    data: AssignmentCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from app.modules.approvals.exceptions import ApprovalRequiredError

    try:
        return await checkout(db, org_id, data, current_user.id)
    except ApprovalRequiredError as exc:
        # Translate the approvals gate into a 409 with the same stable
        # code the warehouse module answers with, so the frontend gate that
        # recognises APPROVAL_REQUIRED works on this door too.
        raise ConflictException('APPROVAL_REQUIRED', str(exc)) from exc


@router.post('/assignments/{assignment_id}/checkin', response_model=AssignmentSchema)
async def checkin_asset(
    assignment_id: UUID,
    data: AssignmentCheckin,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await checkin(db, org_id, assignment_id, data, current_user.id)


@router.get('/assignments', response_model=AssignmentListResponse)
async def list_assignments(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    assignments, total = await list_active_assignments(
        db, org_id, limit=limit, offset=offset
    )
    return AssignmentListResponse.from_slice(
        items=assignments, offset=offset, limit=limit, total=total
    )


@router.get(
    '/assignments/item/{item_id}',
    response_model=PaginatedResponse[AssignmentSchema],
)
async def item_assignment_history(
    item_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    rows = await get_item_assignment_history(
        db, org_id, item_id, limit=limit, offset=offset
    )
    total = await count_item_assignment_history(db, org_id, item_id)
    return PaginatedResponse.from_slice(rows, offset=offset, limit=limit, total=total)


@router.get('/assignments/overdue', response_model=OverdueAssignmentListResponse)
async def list_overdue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """List overdue (return-date passed, not yet returned) assignments."""
    return await list_overdue_assignments(db, org_id, limit=limit, offset=offset)
