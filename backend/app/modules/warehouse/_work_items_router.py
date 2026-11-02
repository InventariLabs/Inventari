from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import map_service_errors

from ._schemas_putaway_done import PutawayDone
from ._schemas_work_items import (
    PutawayDo,
    WorkItemAssign,
    WorkItemCustomCreate,
    WorkItemDone,
    WorkItemMeasures,
    WorkItemSchema,
)
from .putaway_work_service import put_away_async
from .work_board_service import work_measures_async
from .work_item_service import (
    assign_work_item_async,
    create_custom_item_async,
    delete_custom_item_async,
    set_custom_item_done_async,
)

# What To do cannot derive: the person a task is for, and the tasks the boss
# types in — and the one task whose doing is a posting of its own, putting
# away what a receiving area holds. The list itself is read through ``GET /todo``. The
# ``warehouse:write`` grant is mounted on the parent router, so every route
# here is a write by the HTTP method alone.
router = APIRouter(prefix='/work-items')


@router.get('/measures', response_model=WorkItemMeasures)
async def get_work_measures(
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WorkItemMeasures:
    """The strip above the work board: this week's dock-to-stock time and
    how many dispatches left on the day they were raised."""
    return await work_measures_async(db, org_id)


@router.put(
    '/{source_kind}/{source_id}/assignee', status_code=status.HTTP_204_NO_CONTENT
)
async def assign_work_item(
    source_kind: Annotated[str, Path(pattern=r'^[a-z][a-z0-9_]{0,47}$')],
    source_id: UUID,
    data: WorkItemAssign,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    """Give a task to a person, or send it back to nobody with ``null``.

    ``only_if_unassigned`` claims a task that is still nobody's and answers
    409 when somebody else took it first, so a person tapping a stale row
    does not take it from its holder.
    """
    await assign_work_item_async(
        db,
        org_id,
        current_user.id,
        source_kind=source_kind,
        source_id=source_id,
        assignee_id=data.assignee_id,
        only_if_unassigned=data.only_if_unassigned,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    '/custom', response_model=WorkItemSchema, status_code=status.HTTP_201_CREATED
)
async def create_custom_work_item(
    data: WorkItemCustomCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WorkItemSchema:
    """Add a task of your own: a title, and optionally a person and a day."""
    row = await create_custom_item_async(
        db,
        org_id,
        current_user.id,
        title=data.title,
        assignee_id=data.assignee_id,
        due_date=data.due_date,
    )
    return WorkItemSchema(
        key=f'custom:{row.id}',
        kind='custom',
        state='todo',
        source_kind='custom',
        source_id=row.id,
        due_date=row.due_date,
        assignee_id=row.assignee_id,
        subject=row.title,
    )


@router.put('/custom/{item_id}/done', status_code=status.HTTP_204_NO_CONTENT)
async def set_custom_work_item_done(
    item_id: UUID,
    data: WorkItemDone,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    """Tick a custom task off, or take the tick back."""
    await set_custom_item_done_async(
        db, org_id, current_user.id, item_id, done=data.done
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete('/custom/{item_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_work_item(
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    """Remove a custom task."""
    await delete_custom_item_async(db, org_id, current_user.id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    '/putaway/{line_id}',
    response_model=PutawayDone,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def put_away_work_item(
    line_id: UUID,
    data: PutawayDo,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Put away what one receipt line left in a receiving area: post the move (MM).

    The answer carries ``home_shelf`` when the shelf used is worth asking about.
    """
    moved, offer = await put_away_async(
        db,
        org_id,
        current_user.id,
        line_id,
        location_id=data.location_id,
        scanned_code=data.scanned_code,
    )
    return PutawayDone.model_validate(moved).model_copy(update={'home_shelf': offer})
