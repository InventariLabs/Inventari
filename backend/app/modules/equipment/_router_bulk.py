from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    AppException,
    ServiceRejectionError,
    map_service_errors,
)
from app.core.interceptors import InterceptorError
from app.i18n.service import get_current_lang, get_error_message

from ._assets_service import list_matching_asset_ids_async
from .bulk_service import row_error
from .schemas import (
    AssetFilter,
    BulkArchiveResult,
    BulkCheckinRequest,
    BulkCheckinResult,
    BulkEditRequest,
    BulkEditResult,
    BulkEquipmentCreate,
    BulkEquipmentResponse,
    BulkPurgeError,
    BulkPurgeResult,
    BulkRetireResult,
)
from .services import (
    archive_item,
    bulk_checkin_items,
    bulk_create_items,
    bulk_edit_items,
    retire_item,
)

router = APIRouter()

# One request walks the matches one by one, so it has to stop somewhere:
# above this many, the caller is told to narrow the filters. A background
# queue with a progress banner is the next step once an organization
# actually runs into this line (ERPNext went the same way, frappe#22561).
BULK_FILTER_CEILING = 1000


async def _for_each(
    item_ids: list[UUID],
    act: Callable[[UUID], Awaitable[None]],
) -> tuple[int, list[dict[str, str]]]:
    """Apply ``act`` to every id; a rejection is one row's, not the batch's."""
    done = 0
    errors: list[dict[str, str]] = []
    for item_id in item_ids:
        try:
            await act(item_id)
            done += 1
        except (HTTPException, InterceptorError, ValueError, SQLAlchemyError) as exc:
            # A checked-out asset (interceptor veto) or a bad state
            # transition is reported per row, like every other rejection.
            errors.append({'item_id': str(item_id), **row_error(exc)})
    return done, errors


async def _ids_matching(
    db: AsyncSession, org_id: UUID, scope: AssetFilter
) -> list[UUID]:
    """The ids a filter-scoped action will touch, or a refusal above the ceiling."""
    item_ids = await list_matching_asset_ids_async(db, org_id, **scope.model_dump())
    if len(item_ids) > BULK_FILTER_CEILING:
        raise AppException(
            status_code=422,
            code='BULK_SCOPE_TOO_LARGE',
            message=get_error_message(
                'equipment_bulk_scope_too_large',
                get_current_lang(),
                matched=len(item_ids),
                limit=BULK_FILTER_CEILING,
            ),
            extra={'matched': len(item_ids), 'limit': BULK_FILTER_CEILING},
        )
    return item_ids


@router.post(
    '/items/bulk',
    response_model=BulkEquipmentResponse,
    status_code=201,
    # A gate, not a value: the service files under current_user's organization.
    dependencies=[Depends(require_org)],
)
@map_service_errors
async def bulk_create_equipment(
    data: BulkEquipmentCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
) -> Any:
    return await bulk_create_items(db, data, current_user)


@router.post('/items/{item_id}/retire', status_code=204)
@map_service_errors
async def retire_equipment(
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> None:
    try:
        await retire_item(db, org_id, item_id, current_user)
    except InterceptorError as exc:
        # Same state conflict as DELETE /items/{id} — 409 with the
        # interceptor's code, matching the core delete shape. (An invalid
        # state-machine transition, e.g. RETIRED -> RETIRED, is the plain
        # ValueError the decorator turns into the 400 envelope.)
        raise AppException(
            status_code=409,
            code=exc.error_code or 'EQUIPMENT_ASSIGNED',
            message=exc.message,
        ) from exc
    return None


@router.post('/items/{item_id}/archive', status_code=204)
async def archive_equipment(
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> None:
    # Archiving is the soft delete — retiring only sets the status.
    try:
        await archive_item(db, org_id, item_id, current_user)
    except InterceptorError as exc:
        # The assignment interceptor rejects deleting a checked-out asset.
        # Without this the error escaped as a 500 (audit 2026-08-16).
        raise AppException(
            status_code=409,
            code=exc.error_code or 'EQUIPMENT_ASSIGNED',
            message=exc.message,
        ) from exc
    return None


@router.post('/items/bulk-return', response_model=BulkCheckinResult)
async def bulk_return_equipment(
    data: BulkCheckinRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> BulkCheckinResult:
    # One checkin condition for the whole batch — the leaving
    # employee returns five devices at once.
    checked_in, errors = await bulk_checkin_items(
        db,
        org_id,
        data.item_ids,
        data.checkin_condition,
        data.checkin_notes,
        current_user.id,
        return_location_id=data.return_location_id,
    )
    return BulkCheckinResult(checked_in=checked_in, errors=errors)


@router.post('/items/bulk-retire', response_model=BulkRetireResult)
async def bulk_retire_equipment(
    item_ids: list[UUID],
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> BulkRetireResult:
    retired, errors = await _for_each(
        item_ids,
        lambda item_id: retire_item(db, org_id, item_id, current_user, bulk=True),
    )
    return BulkRetireResult(retired=retired, errors=errors)


@router.post('/items/bulk-archive', response_model=BulkArchiveResult)
async def bulk_archive_equipment(
    item_ids: list[UUID],
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> BulkArchiveResult:
    archived, errors = await _for_each(
        item_ids, lambda item_id: archive_item(db, org_id, item_id, current_user)
    )
    return BulkArchiveResult(archived=archived, errors=errors)


@router.post('/assets/matching/retire', response_model=BulkRetireResult)
async def retire_matching_equipment(
    scope: AssetFilter,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> BulkRetireResult:
    """Retire every asset the list's filters match, not just one page of ids."""
    item_ids = await _ids_matching(db, org_id, scope)
    retired, errors = await _for_each(
        item_ids,
        lambda item_id: retire_item(db, org_id, item_id, current_user, bulk=True),
    )
    return BulkRetireResult(retired=retired, errors=errors)


@router.post('/assets/matching/archive', response_model=BulkArchiveResult)
async def archive_matching_equipment(
    scope: AssetFilter,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> BulkArchiveResult:
    """Archive every asset the list's filters match, not just one page of ids."""
    item_ids = await _ids_matching(db, org_id, scope)
    archived, errors = await _for_each(
        item_ids, lambda item_id: archive_item(db, org_id, item_id, current_user)
    )
    return BulkArchiveResult(archived=archived, errors=errors)


@router.post('/items/bulk-purge', response_model=BulkPurgeResult)
async def bulk_purge_equipment(
    item_ids: list[UUID],
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_PURGE),
    org_id: UUID = Depends(require_org),
) -> BulkPurgeResult:
    # One threshold for the same operation — items:purge decides here, exactly
    # like the core DELETE /items/{id}/purge (no separate admin gate).
    from app.core.public_api import core_api

    purged = 0
    errors: list[BulkPurgeError] = []
    for item_id in item_ids:
        try:
            if await core_api.items.purge_async(db, org_id, item_id, current_user):
                purged += 1
            else:
                errors.append(
                    BulkPurgeError(
                        item_id=str(item_id),
                        **row_error(ServiceRejectionError('item_not_found')),
                    )
                )
        except PermissionError as exc:
            # Permanent deletion disabled for the organization — reported per
            # row, like every other rejection.
            errors.append(BulkPurgeError(item_id=str(item_id), **row_error(exc)))
        except InterceptorError as exc:
            # A before_purge veto (posted document lines, stock-take evidence)
            # is a per-row rejection — it must not sink the batch. The code and
            # blocker list travel with it, so a caller can tell the reasons
            # apart without reading the message.
            errors.append(
                BulkPurgeError(
                    item_id=str(item_id),
                    **row_error(exc),
                    blocks=(exc.details or {}).get('blocks'),
                )
            )
        except ValueError as exc:
            errors.append(BulkPurgeError(item_id=str(item_id), **row_error(exc)))
    return BulkPurgeResult(purged=purged, errors=errors)


@router.patch('/assets/bulk', response_model=BulkEditResult)
async def bulk_edit_equipment(
    data: BulkEditRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> BulkEditResult:
    # Status / location / assignment changes for one or more items. Single-item
    # edits reuse the same path with a one-element `item_ids` list.
    updated, errors = await bulk_edit_items(
        db, org_id, data.item_ids, data.action, data.data, current_user.id
    )
    return BulkEditResult(updated=updated, errors=errors)
