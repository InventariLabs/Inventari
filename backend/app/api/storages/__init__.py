from fastapi import APIRouter, status

from app.core.contracts import SystemPermission
from app.core.deps import require_permission
from app.schemas.item import Item as ItemSchema
from app.schemas.pagination import PaginatedResponse
from app.schemas.storage_location import (
    ArchivedStorageLocation,
    StorageCodes,
    StorageLocationBreadcrumb,
    StorageLocationNode,
    StorageLocationSummary,
    StorageNumberResponse,
    StorageReorgResponse,
)
from app.schemas.storage_location import (
    StorageLocation as StorageLocationSchema,
)

from ._reads import (
    get_storage_breadcrumb,
    get_storage_codes,
    get_storage_detail,
    get_storage_items,
    get_storage_summary,
    get_storage_tree,
    get_storages,
    list_archived_storages,
    print_storage_label,
)
from ._writes import (
    archive_storage,
    create_storage,
    create_storage_hierarchy,
    delete_storage,
    generate_storage_code,
    mark_storages_reprinted,
    number_storage_branch,
    reorg_storages,
    set_storage_code_template,
    unarchive_storage,
    update_storage,
)

router = APIRouter()

# Declared next to the route table rather than in each handler's signature:
# the writes live in their own module, and a route added later lands in this
# list, where an unguarded neighbour is visible. A storage name travels onto
# printed labels, so a read-only account writing here is not a cosmetic bug.
_WRITE = [require_permission(SystemPermission.STORAGES_WRITE)]

router.add_api_route(
    '',
    get_storages,
    methods=['GET'],
    response_model=PaginatedResponse[StorageLocationSummary],
)
router.add_api_route(
    '/tree',
    get_storage_tree,
    methods=['GET'],
    # list-envelope-exception: one nested tree, a page boundary would cut a branch
    response_model=list[StorageLocationNode],
)
# Registered before '/{location_id}': a literal segment must win over the
# path parameter, or "archived" is read as an id.
router.add_api_route(
    '/archived',
    list_archived_storages,
    methods=['GET'],
    response_model=PaginatedResponse[ArchivedStorageLocation],
)
router.add_api_route(
    '/hierarchy',
    create_storage_hierarchy,
    methods=['POST'],
    dependencies=_WRITE,
    response_model=StorageLocationSchema,
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    '/reorg',
    reorg_storages,
    methods=['POST'],
    dependencies=_WRITE,
    response_model=StorageReorgResponse,
)
router.add_api_route(
    '/reprinted',
    mark_storages_reprinted,
    methods=['POST'],
    dependencies=_WRITE,
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    '/{location_id}/codes',
    get_storage_codes,
    methods=['GET'],
    response_model=StorageCodes,
)
router.add_api_route(
    '/{location_id}/code-template',
    set_storage_code_template,
    methods=['PUT'],
    dependencies=_WRITE,
    response_model=StorageCodes,
)
router.add_api_route(
    '/{location_id}/number',
    number_storage_branch,
    methods=['POST'],
    dependencies=_WRITE,
    response_model=StorageNumberResponse,
)
router.add_api_route(
    '/{location_id}/archive',
    archive_storage,
    methods=['POST'],
    dependencies=_WRITE,
    response_model=StorageLocationSchema,
)
router.add_api_route(
    '/{location_id}/unarchive',
    unarchive_storage,
    methods=['POST'],
    dependencies=_WRITE,
    response_model=StorageLocationSchema,
)
router.add_api_route(
    '',
    create_storage,
    methods=['POST'],
    dependencies=_WRITE,
    response_model=StorageLocationSchema,
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    '/{location_id}/breadcrumb',
    get_storage_breadcrumb,
    methods=['GET'],
    # list-envelope-exception: the path from the root to one location
    response_model=list[StorageLocationBreadcrumb],
)
router.add_api_route(
    '/{location_id}',
    get_storage_detail,
    methods=['GET'],
    response_model=StorageLocationSchema,
)
router.add_api_route(
    '/{location_id}',
    update_storage,
    methods=['PUT'],
    dependencies=_WRITE,
    response_model=StorageLocationSchema,
)
router.add_api_route(
    '/{location_id}',
    delete_storage,
    methods=['DELETE'],
    dependencies=_WRITE,
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    '/{location_id}/summary',
    get_storage_summary,
    methods=['GET'],
    response_model=StorageLocationSummary,
)
router.add_api_route(
    '/{location_id}/generate-code',
    generate_storage_code,
    methods=['POST'],
    dependencies=_WRITE,
    response_model=StorageLocationSchema,
)
router.add_api_route(
    '/{location_id}/print',
    print_storage_label,
    methods=['GET'],
    response_model=None,
)
router.add_api_route(
    '/{location_id}/items',
    get_storage_items,
    methods=['GET'],
    response_model=PaginatedResponse[ItemSchema],
)
