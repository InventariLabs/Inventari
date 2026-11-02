from uuid import UUID

from fastapi import Depends, Response, status

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    catalogue_refusal,
    map_service_errors,
    refusal_code,
    refusal_exception,
    refusal_text,
)
from app.core.interceptors import InterceptorError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.i18n.service import get_current_lang
from app.schemas.storage_location import (
    StorageArchiveRequest,
    StorageCodeTemplateUpdate,
    StorageHierarchyCreate,
    StorageLocationCreate,
    StorageLocationUpdate,
    StorageNumberRequest,
    StorageReorgRequest,
    StorageReprintedRequest,
)
from app.services.storage._queries import ensure_short_code_async
from app.services.storage._queries import get_storage_async as svc_get_storage
from app.services.storage._reorg import (
    execute_storage_reorg as svc_execute_storage_reorg,
)
from app.services.storage._writes import archive_storage as svc_archive_storage
from app.services.storage._writes import create_storage as svc_create_storage
from app.services.storage._writes import delete_storage as svc_delete_storage
from app.services.storage._writes import unarchive_storage as svc_unarchive_storage
from app.services.storage._writes import update_storage as svc_update_storage
from app.services.storage_hierarchy_service import (
    create_storage_hierarchy as svc_create_storage_hierarchy,
)

logger = get_logger(__name__)


@map_service_errors
async def create_storage_hierarchy(
    data: StorageHierarchyCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Atomically create a full location chain: [Site →] [Zone →] Storage."""
    # A router docstring is the endpoint's public description in the schema, so
    # the reason lives here instead: every ``ValueError`` used to become a 404,
    # and somebody adding a second shelf to a zone was told the location did
    # not exist. The service raises ``NotFoundException`` where a referenced
    # record really is missing, and the canonical mapping (§3) takes the rest
    # to 400 with the reason the service gave.
    require_org(current_user)

    return await svc_create_storage_hierarchy(db, data, current_user)


async def create_storage(
    storage_in: StorageLocationCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Create new storage location."""
    try:
        return await svc_create_storage(db, storage_in, current_user)
    except ValueError as exc:
        raise refusal_exception(exc) from exc


async def update_storage(
    location_id: UUID,
    storage_in: StorageLocationUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Update storage location."""
    org_id = require_org(current_user)
    storage_model = await svc_get_storage(db, org_id, location_id)
    if storage_model is None:
        raise NotFoundException('storage', get_current_lang())
    try:
        return await svc_update_storage(db, storage_model, storage_in, current_user)
    except ValueError as exc:
        # A name or short-code collision now arrives already typed as a 409
        # from the service, so what is left here is ordinary invalid input.
        # This clause used to call every one of them a conflict.
        raise refusal_exception(exc) from exc


async def reorg_storages(
    data: StorageReorgRequest,
    response: Response,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Apply a batch of storage tree operations in one transaction.

    Structural or business violations reject the whole batch (applied=False)
    with per-operation reasons; nothing is written. A refused batch answers
    207 Multi-Status so the wire itself distinguishes "saved" from "none of
    it saved" — a 200 over a rejected batch read as success. A dry run saves
    nothing by design and answers 200 with what each move would carry.
    """
    require_org(current_user)
    result = await svc_execute_storage_reorg(db, data, current_user)
    if data.operations and not result.applied and not data.dry_run:
        response.status_code = 207  # Multi-Status: refused, reasons inside
    return result


async def archive_storage(
    location_id: UUID,
    data: StorageArchiveRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Archive a storage location, optionally moving its items out first."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    storage_model = await svc_get_storage(db, org_id, location_id)
    if storage_model is None:
        raise NotFoundException('storage', lang)
    try:
        return await svc_archive_storage(db, storage_model, data, current_user)
    except ValueError as exc:
        raise refusal_exception(exc) from exc


async def unarchive_storage(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Restore an archived storage location."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    storage_model = await svc_get_storage(db, org_id, location_id)
    if storage_model is None:
        raise NotFoundException('storage', lang)
    try:
        return await svc_unarchive_storage(db, storage_model, current_user)
    except ValueError as exc:
        raise refusal_exception(exc) from exc


async def delete_storage(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Delete storage location."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    storage_model = await svc_get_storage(db, org_id, location_id)
    if storage_model is None:
        raise NotFoundException('storage', lang)

    items_count = await core_api.locations.count_items_in_location_async(
        db, org_id, location_id
    )
    if items_count > 0:
        raise catalogue_refusal('storage_delete_failed_items')

    try:
        await svc_delete_storage(db, storage_model, current_user)
    except InterceptorError as exc:
        # pattern: an interceptor vetoing the delete is a state
        # conflict (e.g. production orders pinning the location), not a
        # request-validation error — 409 with the interceptor's code.
        raise AppException(
            status_code=status.HTTP_409_CONFLICT,
            code=exc.error_code or 'INTERCEPTOR_ERROR',
            message=exc.message,
            extra=exc.details,
        ) from exc
    except ValueError as exc:
        # Service layer raises ValueError for business-rule violations:
        # - Items still in location
        # - StockMove ledger references this storage (audit immutability)
        # - Concurrent transaction inserted stock moves between our check
        #   and the DELETE (TOCTOU)
        # Map to a 409 Conflict so the client gets a structured error
        # instead of a 500.
        raise ConflictException(
            code=refusal_code(exc, 'STORAGE_HAS_DEPENDENCIES'),
            message=refusal_text(exc),
        ) from exc
    return None


async def generate_storage_code(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Assigns a short_code (LOC-XXXX) to a storage location that doesn't have one yet."""
    org_id = require_org(current_user)
    storage_model = await svc_get_storage(db, org_id, location_id)
    if storage_model is None:
        raise NotFoundException('storage')
    return await ensure_short_code_async(db, storage_model, user_id=current_user.id)


async def _codes_of(db, org_id: UUID, location_id: UUID) -> dict:
    from app.services.storage._codes import warehouse_codes_async

    codes = await warehouse_codes_async(db, org_id, location_id)
    if codes is None:
        raise NotFoundException('storage')
    return codes


async def set_storage_code_template(
    location_id: UUID,
    data: StorageCodeTemplateUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Set the code template of a warehouse (a top-level location).

    Rewrites no code: renumbering is a separate step.
    """
    from app.services.storage._codes import set_template_async

    org_id = require_org(current_user)
    warehouse = await svc_get_storage(db, org_id, location_id)
    if warehouse is None:
        raise NotFoundException('storage')
    await set_template_async(db, org_id, current_user.id, warehouse, data.template)
    return await _codes_of(db, org_id, location_id)


async def number_storage_branch(
    location_id: UUID,
    data: StorageNumberRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Give a warehouse, or a branch of one, the codes its template makes.

    Every code that changes stays behind as a pool label aimed at its
    location, so the sticker on the shelf keeps scanning; the answer lists
    the changes, and ``codes.reprint`` the stickers to replace.
    """
    from app.services.storage._codes import number_branch_async

    org_id = require_org(current_user)
    changes = await number_branch_async(
        db, org_id, current_user.id, location_id, renumber=data.renumber
    )
    return {
        'changes': [
            {
                'id': change.location.id,
                'name': change.location.name,
                'old_code': change.old_code,
                'new_code': change.new_code,
            }
            for change in changes
        ],
        'codes': await _codes_of(db, org_id, location_id),
    }


async def mark_storages_reprinted(
    data: StorageReprintedRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
) -> Response:
    """The new stickers of these locations are on the shelves.

    The old codes keep scanning; the locations leave the list to reprint.
    """
    from app.services.storage._codes import mark_reprinted_async

    org_id = require_org(current_user)
    await mark_reprinted_async(db, org_id, current_user.id, data.location_ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
