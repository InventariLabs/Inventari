from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._items_actions import router as actions_router
from app.api._items_crud import router as crud_router
from app.api._items_images import router as images_router
from app.api._items_import_export import router as import_export_router
from app.api._items_params import parse_template_ids
from app.api._items_product_templates import router as templates_router
from app.api._items_queries import router as queries_router
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.db_utils import LIST_COUNT_CAP
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_permission,
)
from app.core.exceptions import (
    map_service_errors,
    refusal_exception,
)
from app.core.public_api import core_api
from app.schemas._common import BulkUpdateResponse
from app.schemas.item import (
    Item as ItemSchema,
)
from app.schemas.item import (
    ItemBulkUpdate,
    ItemCreate,
    ItemListResponse,
)
from app.services.items import (
    bulk_update_items as bulk_update_items_service,
)
from app.services.items import (
    create_item as create_item_service,
)
from app.services.items import (
    get_items as get_items_service,
)

router = APIRouter()
router.include_router(import_export_router)
router.include_router(queries_router)
# templates_router must be registered before crud_router: its
# `/product-templates` (no path param) would otherwise be swallowed by
# `/{item_id}` (UUID) → 422 (template autocomplete).
router.include_router(templates_router)
router.include_router(crud_router)
router.include_router(actions_router)
router.include_router(images_router)


@router.get('', response_model=ItemListResponse)
async def get_items(
    location_id: UUID | None = Query(None, description='Filter by location'),
    category_id: UUID | None = Query(None, description='Filter by category'),
    context_tag: str | None = Query(
        None, description='Filter by category context_tag (e.g. equipment)'
    ),
    exclude_module_contexts: bool = Query(
        False,
        description='Hide items whose category belongs to a vertical module',
    ),
    location_usage: str | None = Query(
        'internal',
        description='Filter by location usage (internal, customer, inventory)',
    ),
    include_empty: bool = Query(
        False,
        description=(
            'Also return records with nothing left (quantity <= 0), wherever '
            'they sit — consuming the last unit files one under the virtual '
            'Consumed location, outside the internal default.'
        ),
    ),
    search: str | None = Query(
        None, description='Search by name, brand, barcode or label code'
    ),
    expiring_days: int | None = Query(
        None, description='Products expiring within X days'
    ),
    only_expired: bool = Query(False, description='Show only expired items'),
    only_low_stock: bool = Query(False, description='Show only low stock items'),
    needs_attention: bool = Query(
        False,
        description=(
            'Records that need attention: expired, expiring within the '
            'expiry horizon, or of a product at its low-stock threshold — '
            'the records behind GET /items/attention-counts'
        ),
    ),
    low_stock_threshold: float = Query(1.0, description='Threshold for low stock'),
    source_document_id: UUID | None = Query(
        None, description='Filter by source document (e.g. PZ that created the item)'
    ),
    template_ids: str = Query(
        '',
        description=(
            'Comma-separated product template UUIDs. Narrows the list to items '
            'built on those templates; a module supplies the set (e.g. the '
            'templates that have a formula). Empty means no filter.'
        ),
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(
        None, description='Field to sort by (created_at, name, quantity, expiry_date)'
    ),
    sort_order: str = Query('desc', pattern='^(asc|desc)$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """List of all user's products with advanced filters and pagination."""

    # An empty value is "no filter", never "match nothing" — a chip whose ids
    # have not loaded yet must not blank the list.
    parsed_template_ids = parse_template_ids(template_ids)

    claimed_tags: set[str] = set()
    if exclude_module_contexts:
        from app.core.module_scope import get_claimed_context_tags

        claimed_tags = get_claimed_context_tags()

    # An explicit storage ask is more specific than the usage default: the
    # virtual counterparts hold real records — the item the reader consumed
    # to zero lives in one, and this list (the virtual location's "Open") is
    # its way back into view.
    if location_id is not None and location_usage == 'internal':
        location_usage = None

    # Expiry filters cut on the organization's day, not the server's.
    today = (
        await core_api.organizations.today_async(db, current_user.organization_id)
        if current_user.organization_id is not None
        else None
    )

    items, total = await db.run_sync(
        lambda s: get_items_service(
            db=s,
            user=current_user,
            storage_id=location_id,
            category_id=category_id,
            context_tag=context_tag,
            claimed_tags=claimed_tags or None,
            location_usage=location_usage,
            include_empty=include_empty,
            search=search,
            expiring_days=expiring_days,
            only_expired=only_expired,
            only_low_stock=only_low_stock,
            needs_attention=needs_attention,
            low_stock_threshold=low_stock_threshold,
            offset=offset,
            limit=limit,
            # The scope is the reader's organization, named rather than
            # listed location by location: the page is then walked in the
            # organization's index order instead of read whole and sorted.
            user_organization_id=current_user.organization_id,
            sort_by=sort_by,
            sort_order=sort_order,
            source_document_id=source_document_id,
            template_ids=parsed_template_ids or None,
            today=today,
            # A large organization's list is not counted to the last row on
            # every page; the footer's sums carry the exact count.
            count_cap=LIST_COUNT_CAP,
        )
    )

    return ItemListResponse.from_slice(
        items=[ItemSchema.model_validate(i) for i in items],
        offset=offset,
        limit=limit,
        total=total,
        count_cap=LIST_COUNT_CAP,
    )


@router.post('', response_model=ItemSchema, status_code=status.HTTP_201_CREATED)
@map_service_errors
async def create_item(
    item_in: ItemCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Add product manually.

    ``unit_confirmed_over_template`` travels on the body (see ``ItemCreate``):
    a unit that differs from the matched product template's is a deliberate
    choice, and the request has to say so before the record is written.

    Refusals are answered by the canonical mapping: the item limit
    (``QuotaExceededError``) in the same envelope the scan door gives it, and
    nothing else that travels this chain as a ``PermissionError`` borrows the
    limit's words.
    """
    return await create_item_service(db=db, item_in=item_in, user=current_user)


@router.patch(
    '/bulk', response_model=BulkUpdateResponse, status_code=status.HTTP_200_OK
)
async def bulk_update_items(
    bulk_data: ItemBulkUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Bulk update multiple items."""
    try:
        count = await bulk_update_items_service(
            db=db, bulk_data=bulk_data, user=current_user
        )
        return {'updated': count}
    except ValueError as exc:
        raise refusal_exception(exc) from exc
