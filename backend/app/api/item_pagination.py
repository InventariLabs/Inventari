"""Cursor-paginated endpoints for items — history feed and infinite-scroll list.

Mounted at the same ``/items`` prefix as the main ``items`` router in ``main.py``.
Kept in a separate module to keep ``api/items.py`` under the 500-LOC threshold.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_user_storage_ids
from app.core.contracts import SystemPermission
from app.core.cursor import decode_cursor, encode_cursor
from app.core.deps import get_async_db, require_permission
from app.core.public_api import core_api
from app.schemas.item import Item as ItemSchema
from app.schemas.item_history import ItemHistorySchema
from app.schemas.pagination import CursorPaginatedResponse
from app.services.identity_service import get_current_user

router = APIRouter()


@router.get('/history', response_model=CursorPaginatedResponse[ItemHistorySchema])
async def get_items_history(
    limit: int = Query(
        20, ge=1, le=200, description='Number of history entries to return'
    ),
    cursor: str | None = Query(
        None, description='Opaque cursor from previous response'
    ),
    context_tag: str | None = Query(
        None, description='Filter by category context_tag (e.g. equipment)'
    ),
    exclude_module_contexts: bool = Query(
        False, description='Hide entries for items owned by a vertical module'
    ),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user=Depends(get_current_user),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
) -> CursorPaginatedResponse[ItemHistorySchema]:
    """Get recent activity history for user's items (cursor-paginated, newest first)."""
    cursor_ts = None
    if cursor:
        _, cursor_ts = decode_cursor(cursor)

    claimed_tags: set[str] = set()
    if exclude_module_contexts:
        from app.core.module_scope import get_claimed_context_tags

        claimed_tags = get_claimed_context_tags()

    from app.services.item_history_service import list_by_storage_ids_async

    entries = await list_by_storage_ids_async(
        db,
        user_storage_ids,
        cursor_ts=cursor_ts,
        limit=limit + 1,
        context_tag=context_tag,
        claimed_tags=claimed_tags or None,
    )

    has_more = len(entries) > limit
    page = entries[:limit]

    next_cursor = (
        encode_cursor(page[-1].id, page[-1].created_at) if has_more and page else None
    )

    items = [
        ItemHistorySchema(
            id=e.id,
            item_id=e.item_id,
            organization_id=e.organization_id,
            user_id=e.user_id,
            action=e.action,
            changes=e.changes,
            created_at=e.created_at,
            item_name=e.item.name if e.item else None,
            user_name=(e.user.full_name or e.user.email) if e.user else None,
            source_document_id=e.source_document_id,
        )
        for e in page
    ]
    return CursorPaginatedResponse(
        items=items, next_cursor=next_cursor, has_more=has_more
    )


@router.get(
    '/{item_id}/history', response_model=CursorPaginatedResponse[ItemHistorySchema]
)
async def get_item_history(
    item_id: UUID,
    limit: int = Query(
        50, ge=1, le=200, description='Number of history entries to return'
    ),
    cursor: str | None = Query(
        None, description='Opaque cursor from previous response'
    ),
    current_user=Depends(get_current_user),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
) -> CursorPaginatedResponse[ItemHistorySchema]:
    """Get movement/action history for a single item."""
    cursor_ts = None
    if cursor:
        _, cursor_ts = decode_cursor(cursor)

    from app.services.item_history_service import list_for_item_async

    entries = await list_for_item_async(
        db,
        item_id,
        current_user.organization_id,
        cursor_ts=cursor_ts,
        limit=limit + 1,
    )

    has_more = len(entries) > limit
    page = entries[:limit]

    next_cursor = (
        encode_cursor(page[-1].id, page[-1].created_at) if has_more and page else None
    )

    items = [
        ItemHistorySchema(
            id=e.id,
            item_id=e.item_id,
            organization_id=e.organization_id,
            user_id=e.user_id,
            action=e.action,
            changes=e.changes,
            created_at=e.created_at,
            item_name=e.item.name if e.item else None,
            user_name=(e.user.full_name or e.user.email) if e.user else None,
            source_document_id=e.source_document_id,
        )
        for e in page
    ]
    return CursorPaginatedResponse(
        items=items, next_cursor=next_cursor, has_more=has_more
    )


@router.get('/cursor-page', response_model=CursorPaginatedResponse[ItemSchema])
async def get_items_cursor_page(
    cursor: str | None = Query(
        None, description='Opaque cursor from previous response'
    ),
    limit: int = Query(50, ge=1, le=200),
    location_id: UUID | None = Query(None),
    search: str | None = Query(None),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user=Depends(get_current_user),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
) -> CursorPaginatedResponse[ItemSchema]:
    """Cursor-paginated items list. Suitable for infinite-scroll UIs."""
    cursor_ts = None
    cursor_id = None
    if cursor:
        cursor_id, cursor_ts = decode_cursor(cursor)

    items = await core_api.items.search_cursor_paginated_async(
        db,
        current_user.organization_id,
        storage_ids=user_storage_ids,
        storage_id=location_id,
        search=search,
        cursor_ts=cursor_ts,
        cursor_id=cursor_id,
        limit=limit,
    )

    return CursorPaginatedResponse(
        items=[ItemSchema.model_validate(i) for i in items.items],
        next_cursor=items.next_cursor,
        has_more=items.has_more,
    )
