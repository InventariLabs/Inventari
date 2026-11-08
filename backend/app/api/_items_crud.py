from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_user_storage_ids
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    module_scopes_held,
    require_any_permission,
    require_permission,
)
from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    refusal_exception,
)
from app.core.interceptors import InterceptorError
from app.core.module_ownership import item_belongs_to_module
from app.core.module_scope import get_context_tags_of
from app.schemas.item import (
    Item as ItemSchema,
)
from app.schemas.item import (
    ItemDeleteRequest,
    ItemUpdate,
)
from app.services.items import (
    delete_item as delete_item_service,
)
from app.services.items import (
    purge_item as purge_item_service,
)
from app.services.items import (
    restore_item as restore_item_service,
)
from app.services.items import (
    update_item as update_item_service,
)
from app.services.items._query_get import get_any_item_in_locations_or_404_async
from app.services.items._query_special import get_item_or_404_async

router = APIRouter()

#: The equipment register's asset card (linked from the list and from
#: assignment history) opens a record by id through this Core read; the
#: register's own read admits that card, archived or not. The same names bound
#: the answer: a holder of the module's read opens the module's records only,
#: and a product outside them is 404 — the card is one record, not a second
#: door to the whole product list. Changing or deleting a record keeps the
#: Core write keys.
_MODULE_READS = ('equipment:read',)
_READS_ONE_ITEM = require_any_permission(SystemPermission.ITEMS_READ, *_MODULE_READS)


@router.get('/{item_id}', response_model=ItemSchema)
async def get_item(
    item_id: UUID,
    include_archived: bool = Query(
        False,
        description='Answer an archived product instead of the '
        'archive-pointing 404. A screen whose record stays reachable after '
        'archiving — the Equipment card, linked from assignment history — '
        'asks for it; the live lists never do.',
    ),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = _READS_ONE_ITEM,
):
    """Product details."""
    item = await get_item_or_404_async(
        db, item_id, user_storage_ids, include_archived=include_archived
    )
    if not current_user.has_permission(SystemPermission.ITEMS_READ) and not any(
        item_belongs_to_module(item, module, get_context_tags_of(module))
        for module in module_scopes_held(current_user, _MODULE_READS)
    ):
        raise NotFoundException('item')
    return item


@router.put('/{item_id}', response_model=ItemSchema)
async def update_item(
    item_id: UUID,
    item_in: ItemUpdate,
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Update product."""
    # A request carrying a quantity is a read-modify-write: the service
    # computes ``delta = new - old`` from what is read here, so two edits in
    # flight both measured against the same stale ``old`` and left the
    # record's cache and the stock it stands for at two different numbers.
    item = await get_item_or_404_async(
        db, item_id, user_storage_ids, for_update=item_in.quantity is not None
    )
    try:
        return await update_item_service(
            db=db, item=item, item_in=item_in, user=current_user
        )
    except InterceptorError as exc:
        raise AppException(
            status_code=422,
            code='INTERCEPTOR_ERROR',
            message=exc.message,
        ) from exc
    except ValueError as exc:
        raise refusal_exception(exc) from exc


@router.delete('/{item_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    delete_data: ItemDeleteRequest | None = None,
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_DELETE),
):
    """Soft-delete product (archive). Item is hidden but recoverable."""
    item = await get_any_item_in_locations_or_404_async(db, item_id, user_storage_ids)
    reason = delete_data.reason if delete_data else None
    notes = delete_data.notes if delete_data else None
    try:
        await delete_item_service(db, item, current_user, reason=reason, notes=notes)
    except InterceptorError as exc:
        # an interceptor rejecting the delete is a state conflict
        # (e.g. asset still checked out), not a request-validation error —
        # 409 with the interceptor's code, same shape as the retire path.
        raise AppException(
            status_code=status.HTTP_409_CONFLICT,
            code=exc.error_code or 'INTERCEPTOR_ERROR',
            message=exc.message,
        ) from exc
    except ValueError as exc:
        raise refusal_exception(exc) from exc
    return None


@router.post('/{item_id}/restore', response_model=ItemSchema)
async def restore_item(
    item_id: UUID,
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Restore a soft-deleted product back to active state."""
    item = await get_any_item_in_locations_or_404_async(db, item_id, user_storage_ids)
    try:
        return await restore_item_service(db, item, current_user)
    except ValueError as exc:
        raise refusal_exception(exc) from exc


@router.delete('/{item_id}/purge', status_code=status.HTTP_204_NO_CONTENT)
async def purge_item(
    item_id: UUID,
    reason: str | None = Query(None, max_length=500),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_PURGE),
):
    """Permanently delete an archived product. Cannot be undone."""
    item = await get_any_item_in_locations_or_404_async(db, item_id, user_storage_ids)
    try:
        await purge_item_service(db, item, current_user, reason=reason)
    except PermissionError as exc:
        # the organization disabled permanent deletion — 403 with an
        # explicit code, independent of the caller's permissions.
        raise AppException(
            status_code=status.HTTP_403_FORBIDDEN,
            code='PURGE_DISABLED',
            message=str(exc),
        ) from exc
    except InterceptorError as exc:
        # a module vetoed the purge (posted document lines, stock-take
        # evidence, ...). 409 with the structured blocker list from the
        # interceptor's details — same envelope family as the delete path.
        raise ConflictException(
            code=exc.error_code or 'PURGE_BLOCKED',
            message=exc.message,
            details=exc.details,
        ) from exc
    except ValueError as exc:
        raise refusal_exception(exc) from exc
    return None
