from dataclasses import asdict
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._items_params import parse_template_ids
from app.api.dependencies import get_user_storage_ids
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.module_ownership import hidden_module_tags_async
from app.core.public_api import core_api
from app.schemas.item import (
    ArchivedCategoryBrief,
    ArchivedItemListResponse,
    ArchivedItemSchema,
    AttentionCounts,
    ItemAggregates,
)
from app.schemas.item import (
    Item as ItemSchema,
)
from app.schemas.pagination import PaginatedResponse
from app.services.analytics._common import (
    get_org_currency_async,
    org_today_async,
    org_uses_valuation_layers_async,
)
from app.services.analytics.overview import get_health_counts_async
from app.services.items import (
    get_items_aggregates as get_items_aggregates_service,
)
from app.services.items._query_get import count_needing_attention_async
from app.services.items._query_special import (
    get_archived_items_async,
    get_deletion_notes_async,
    get_expiring_items_async,
)
from app.services.items.low_stock import claimed_tags_for

router = APIRouter()


@router.get('/aggregates', response_model=ItemAggregates)
async def get_items_aggregates_endpoint(
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
            'Also count records with nothing left (quantity <= 0), wherever '
            'they sit — the same rows the list shows with this flag, so the '
            'footer widens with what it sums.'
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
    source_document_id: UUID | None = Query(
        None, description='Filter by source document (e.g. PZ that created the item)'
    ),
    template_ids: str = Query(
        '',
        description='Comma-separated product template UUIDs; empty means no filter.',
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Totals over the whole filtered set, for the list footer.

    Takes the same filters as ``GET /items`` minus pagination and sorting, and
    runs them through the same query builder — the sums cannot drift from the
    rows the list shows. Registered on this router because ``/aggregates``
    must resolve before the CRUD router's ``/{item_id}``.
    """
    parsed_template_ids = parse_template_ids(template_ids)

    claimed_tags: set[str] = set()
    if exclude_module_contexts:
        from app.core.module_scope import get_claimed_context_tags

        claimed_tags = get_claimed_context_tags()

    # Same rule as the list: an explicit storage ask is more specific than
    # the usage default.
    if location_id is not None and location_usage == 'internal':
        location_usage = None

    # Expiry filters cut on the organization's day, not the server's.
    today = (
        await core_api.organizations.today_async(db, current_user.organization_id)
        if current_user.organization_id is not None
        else None
    )

    # Where the value is read from is the organization's choice, not the
    # request's: the statistics and the stock-as-of report beside this list
    # decide it the same way, so the three screens name one source.
    org_id = current_user.organization_id
    has_layers = org_id is not None and await org_uses_valuation_layers_async(
        db, org_id
    )
    org_currency = await get_org_currency_async(db, org_id) if org_id else None

    totals = await db.run_sync(
        lambda s: get_items_aggregates_service(
            db=s,
            # Tenancy, and the same one the list gives: without it the
            # footer would count rows the list no longer shows.
            user_organization_id=current_user.organization_id,
            location_usage=location_usage,
            include_empty=include_empty,
            storage_id=location_id,
            category_id=category_id,
            context_tag=context_tag,
            claimed_tags=claimed_tags or None,
            search=search,
            expiring_days=expiring_days,
            only_expired=only_expired,
            only_low_stock=only_low_stock,
            needs_attention=needs_attention,
            source_document_id=source_document_id,
            template_ids=parsed_template_ids or None,
            today=today,
            has_layers=has_layers,
            org_currency=org_currency,
        )
    )
    answer = asdict(totals)
    # The sentence beside the sum says the statistics total counts what the
    # list leaves out. The statistics follow the organization's own setting
    # (``hidden_module_tags_async``), so where the organization hides module
    # data the tile leaves the same records out and the two figures agree:
    # the sentence would be untrue, and it stands down.
    if (
        answer['excludes_module_items']
        and org_id is not None
        and await hidden_module_tags_async(db, org_id) is not None
    ):
        answer['excludes_module_items'] = False
    return ItemAggregates(**answer)


@router.get('/attention-counts', response_model=AttentionCounts)
async def get_attention_counts_endpoint(
    exclude_module_contexts: bool = Query(
        False,
        description='Hide records whose category belongs to a vertical module',
    ),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """What needs attention, from one rule shared with the statistics screen.

    Expired and expiring-soon records plus short products — the numbers
    the statistics overview reports, from the same service function. The
    dashboard heading and the statistics health card read this one place,
    so the two cannot disagree. ``exclude_module_contexts`` takes the same
    records out of the count that it takes out of the item list, so the
    heading matches the rows the list behind it can open.
    """
    counts = await get_health_counts_async(
        db, org_id, exclude_module_contexts=exclude_module_contexts
    )
    return AttentionCounts(
        expired=counts.expired,
        expiring_soon=counts.expiring_soon,
        low_stock=counts.low_stock,
        records=await count_needing_attention_async(
            db,
            org_id,
            claimed_tags=claimed_tags_for(exclude_module_contexts),
            today=await org_today_async(db, org_id),
        ),
    )


@router.get('/expiring', response_model=PaginatedResponse[ItemSchema])
async def get_expiring_items(
    days: int = Query(7, description='Number of days until expiration'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Products approaching expiration (all locations)."""
    items, total = await get_expiring_items_async(
        db,
        user_storage_ids,
        organization_id=current_user.organization_id,
        days=days,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse.from_slice(items, offset, limit, total)


@router.get('/archived', response_model=ArchivedItemListResponse)
async def get_archived_items(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    context_tag: str | None = Query(
        None, description='Filter by category context_tag (e.g. equipment)'
    ),
    exclude_module_contexts: bool = Query(
        False, description='Hide items whose category belongs to a vertical module'
    ),
    module_scope: str | None = Query(
        None,
        description=(
            'Everything one vertical module counts as its own: filed under a '
            'category it claims, or under no category and marked as its record. '
            'A module archive wants this rather than context_tag, which alone '
            'loses the records saved without a category.'
        ),
    ),
    search: str | None = Query(
        None, description='Search by name, brand, barcode or label code'
    ),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """List of archived (soft-deleted) products, scoped by module context."""
    claimed_tags: set[str] = set()
    if exclude_module_contexts:
        from app.core.module_scope import get_claimed_context_tags

        claimed_tags = get_claimed_context_tags()

    items, total = await get_archived_items_async(
        db,
        user_storage_ids,
        offset=offset,
        limit=limit,
        context_tag=context_tag,
        claimed_tags=claimed_tags or None,
        module_scope=module_scope,
        search=search,
    )
    notes = await get_deletion_notes_async(db, [item.id for item in items])
    result = []
    for item in items:
        result.append(
            ArchivedItemSchema(
                id=item.id,
                name=item.name,
                location_id=item.storage_location_id,
                category_id=item.category_id,
                quantity=float(item.quantity) if item.quantity is not None else 0.0,
                purchase_price=float(item.purchase_price)
                if item.purchase_price
                else None,
                currency=item.currency,
                is_deleted=item.is_deleted,
                deleted_at=item.deleted_at,
                deleted_by=item.deleted_by,
                deletion_reason=item.deletion_reason,
                deletion_notes=notes.get(item.id),
                category=ArchivedCategoryBrief(
                    id=item.category.id,
                    name=item.category.name,
                    code=item.category.code,
                    icon=item.category.icon,
                )
                if item.category
                else None,
            )
        )

    return ArchivedItemListResponse.from_slice(
        items=result, offset=offset, limit=limit, total=total
    )
