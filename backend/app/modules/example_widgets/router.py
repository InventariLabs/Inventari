from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.module_sdk import (
    NotFoundException,
    PaginatedResponse,
    get_async_db,
    get_current_lang,
    get_current_user_context,
    require_module,
    require_org,
    require_read_write,
)

from .schemas import WidgetCreate, WidgetSchema, WidgetUpdate
from .service import (
    create_widget,
    delete_widget,
    get_widget,
    list_widgets,
    update_widget,
)

# Mounted on the router, not on each endpoint: that is what covers the
# endpoints somebody adds later, and it is the half a per-endpoint guard
# always loses. Safe methods need the read key, mutating ones the write key —
# one line for the whole module. This module is what other modules are copied
# from, so what it does here is what they will do.
router = APIRouter(
    dependencies=[
        Depends(require_module('example_widgets')),
        require_read_write('example_widgets:read', 'example_widgets:write'),
    ]
)


@router.get('', response_model=PaginatedResponse[WidgetSchema])
async def list_widgets_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
    # Bounds declared where the request arrives, the way the rest of the
    # codebase declares them. Undeclared, a negative offset went to Postgres
    # and came back as a 500 — and this module is what a new one is copied
    # from, so an oversight here is not one endpoint's oversight.
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[WidgetSchema]:
    widgets, total = await list_widgets(db, org_id, limit=limit, offset=offset)
    return PaginatedResponse[WidgetSchema].from_slice(
        [WidgetSchema.model_validate(w) for w in widgets], offset, limit, total
    )


@router.post('', response_model=WidgetSchema, status_code=status.HTTP_201_CREATED)
async def create_widget_endpoint(
    data: WidgetCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WidgetSchema:
    widget = await create_widget(db, org_id, data, current_user.id)
    return WidgetSchema.model_validate(widget)


@router.get('/{widget_id}', response_model=WidgetSchema)
async def get_widget_endpoint(
    widget_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WidgetSchema:
    widget = await get_widget(db, org_id, widget_id)
    if widget is None:
        raise NotFoundException('widget', get_current_lang())
    return WidgetSchema.model_validate(widget)


@router.patch('/{widget_id}', response_model=WidgetSchema)
async def update_widget_endpoint(
    widget_id: UUID,
    data: WidgetUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WidgetSchema:
    widget = await update_widget(db, org_id, widget_id, data, current_user.id)
    if widget is None:
        raise NotFoundException('widget', get_current_lang())
    return WidgetSchema.model_validate(widget)


@router.delete('/{widget_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget_endpoint(
    widget_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    deleted = await delete_widget(db, org_id, widget_id, current_user.id)
    if not deleted:
        raise NotFoundException('widget', get_current_lang())
