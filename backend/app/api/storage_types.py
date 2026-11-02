from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    StorageTypeCreateDTO,
    StorageTypeDTO,
    StorageTypeUpdateDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    NotFoundException,
    map_service_errors,
    refusal_exception,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang
from app.schemas.pagination import PaginatedResponse

router = APIRouter()

# Everything a profile seeds or a module declares is offered to the user; only
# these are held back. An allow-list would have to grow with every new vertical,
# and did not: four types seeded by the equipment profile and two declared by the
# equipment module never reached the client.
_HIDDEN_CODES = {
    # Type of the virtual locations (consumption, loss, production). Internal
    # bookkeeping, never a place the user picks.
    'SYSTEM',
    # Retired set — kept in the database for organizations that still have
    # locations on them, deliberately absent from the picker.
    'WINE_CELLAR',
    'DRY_STORAGE',
    'TOOLBOX',
    'BOOKSHELF',
    # The profile's retired duplicates of the equipment module's own types:
    # "IT Rack / Server Room" stood beside the module's "Server Room", and
    # "Asset Storage" beside its "IT Storage / Warehouse" — same place, and
    # the pair chose its field set at random. The module's types carry the
    # equipment fields; these stopped being seeded and left the picker.
    'IT_RACK',
    'ASSET_STORAGE',
}


def _filter_and_dedupe(
    types_: list[StorageTypeDTO], extra_hidden: set[str] | None = None
) -> list[StorageTypeDTO]:
    """Group by type_code, hide internal/retired types, keep one row per code.

    Creation refuses a duplicate code within an organization, so live data
    holds at most one row per code to begin with — the dedupe is the last
    line of defense for shapes that predate that refusal. The FIRST row in
    the incoming order wins: the service sorts deterministically, which
    makes the response a function of the data instead of the table's
    physical layout. (Picking the last row left the winner to heap order,
    and a full parallel test run once flipped it.)"""
    hidden = _HIDDEN_CODES | (extra_hidden or set())
    type_map: dict[str, StorageTypeDTO] = {}
    for st in types_:
        if st.type_code in hidden:
            continue
        if st.type_code not in type_map:
            type_map[st.type_code] = st
    return list(type_map.values())


async def _codes_declared_by_disabled_modules(
    db: AsyncSession, org_id: UUID
) -> set[str]:
    """Storage-type codes every module offers that this installation turned off.

    A module's declared types are its vocabulary: the equipment module
    carries "Server Room" and its field set, and an organization without the
    module has nothing that explains those fields. The rows stay in the
    database — locations stand on them, and a disable is not a demolition —
    so the list is the one place that notices: it offers what the
    installation's enabled modules can stand behind, and holds the rest
    back until the module comes back. Matching goes by declared code, which
    is the identity the seeder upserts by, so rows seeded before this rule
    are covered with no backfill.
    """
    from app.core.module_registry import module_registry
    from app.core.modules import is_module_enabled_async

    codes: set[str] = set()
    for module in module_registry.get_all():
        if not module.metadata.storage_types:
            continue
        if await is_module_enabled_async(db, org_id, module.metadata.name):
            continue
        codes.update(decl.code for decl in module.metadata.storage_types)
    return codes


@router.get('', response_model=PaginatedResponse[StorageTypeDTO])
async def get_storage_types(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """
    List of available storage location types, owned by the caller's
    organization (types have had an owner since — the global, shared
    namespace is gone). One row per type_code, in a stable order. Types
    declared by a module the organization does not have enabled are left
    out — see ``_codes_declared_by_disabled_modules``.
    """
    org_id = require_org(current_user)
    types_ = await core_api.location_types.list_for_org_async(db, org_id)
    visible = _filter_and_dedupe(
        types_, await _codes_declared_by_disabled_modules(db, org_id)
    )
    return PaginatedResponse.from_full_list(visible, offset=offset, limit=limit)


@router.post('', response_model=StorageTypeDTO, status_code=status.HTTP_201_CREATED)
async def create_storage_type(
    storage_type_in: StorageTypeCreateDTO,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_WRITE),
):
    """Create a storage location type owned by the caller's organization."""
    require_org(current_user)
    try:
        return await core_api.location_types.create_async(
            db, storage_type_in, current_user, get_current_lang()
        )
    except ValueError as exc:
        raise refusal_exception(exc) from exc


@router.get('/{location_type_id}', response_model=StorageTypeDTO)
async def get_storage_type(
    location_type_id: UUID,
    db=Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """Storage location type details."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    # Org-scoped: returns the type only if owned by the caller's org or a
    # system type — the API can never surface another org's custom type.
    storage_type = await core_api.location_types.get_by_id_async(
        db, location_type_id, org_id
    )
    if not storage_type:
        raise NotFoundException('storage_type', lang)

    return storage_type


@router.put('/{location_type_id}', response_model=StorageTypeDTO)
@map_service_errors
async def update_storage_type(
    location_type_id: UUID,
    storage_type_in: StorageTypeUpdateDTO,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_WRITE),
):
    """
    Update a storage location type.
    If it's a global system type, fork it for the organization first.
    """
    lang = get_current_lang()
    result = await core_api.location_types.update_async(
        db, location_type_id, storage_type_in, current_user, lang
    )
    if result is None:
        raise NotFoundException('storage_type', lang)
    return result


@router.delete('/{location_type_id}', status_code=status.HTTP_204_NO_CONTENT)
@map_service_errors
async def delete_storage_type(
    location_type_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_WRITE),
):
    """Delete a storage location type (only non-system types that are not in use)."""
    lang = get_current_lang()
    deleted = await core_api.location_types.delete_async(
        db, location_type_id, current_user
    )
    if not deleted:
        raise NotFoundException('storage_type', lang)
    return None
