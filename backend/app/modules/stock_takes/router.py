from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    StorageDTO,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_read_write,
)
from app.core.exceptions import (
    AppException,
    ConflictException,
    catalogue_refusal,
    catalogue_status_refusal,
    map_service_errors,
)
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from ._router_cycle_count import router as cycle_count_router
from .cycle_count_service import last_counted_everywhere, open_counts_by_root
from .models import StockTakeItem, StockTakeStatus
from .schemas import (
    CountedLocation,
    LocationCountState,
    ShelfClosed,
    StockTakeComplete,
    StockTakeCreate,
    StockTakeItemCountUpdate,
    StockTakeItemCreate,
    StockTakeItemResponse,
    StockTakeItemWithDetails,
    StockTakeReport,
    StockTakeResponse,
    StockTakeStatusUpdate,
    StockTakeUpdate,
    StockTakeWithDetails,
)
from .stock_take_service import (
    add_surplus_item,
    build_stock_take_report,
    bulk_count_items_and_commit,
    calculate_stock_take_summary,
    close_location,
    count_item_and_commit,
    create_stock_take_from_storage,
    delete_stock_take_entity,
    finalize_stock_take,
    get_stock_take_item_or_404,
    get_stock_take_items_filtered,
    get_stock_take_items_simple,
    get_stock_take_or_404,
    list_closed_locations,
    list_stock_takes_filtered,
    update_stock_take_fields,
    update_stock_take_status_service,
)
from .storage_lookup_service import get_storage_tree, storage_exists

router = APIRouter(
    dependencies=[
        Depends(require_module('stock_takes')),
        require_read_write('stock_takes:read', 'stock_takes:write'),
    ]
)

router.include_router(cycle_count_router)


@router.post('', response_model=StockTakeResponse, status_code=status.HTTP_201_CREATED)
async def create_stock_take(
    stock_take_in: StockTakeCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeResponse:
    """
    Create new inventory.

    Starts new inventory for selected storage location.
    Automatically creates items for all products in that location.
    """
    org_id = require_org(current_user)
    if not await storage_exists(db, org_id, stock_take_in.location_id):
        raise catalogue_status_refusal('storage_not_found', status.HTTP_404_NOT_FOUND)
    stock_take = await create_stock_take_from_storage(
        db=db,
        org_id=org_id,
        user_id=current_user.id,
        storage_location_id=stock_take_in.location_id,
        name=stock_take_in.name,
        description=stock_take_in.description,
        notes=stock_take_in.notes,
        blind_mode=stock_take_in.blind_mode,
        tolerance_percent=stock_take_in.tolerance_percent,
        require_full_count=stock_take_in.require_full_count,
    )
    summary = await calculate_stock_take_summary(stock_take.id, db)
    response = StockTakeResponse.model_validate(stock_take)
    response.items_count = summary['items_count']
    response.counted_items_count = summary['counted_items_count']
    response.discrepancies_count = summary['discrepancies_count']
    return response


@router.get('', response_model=PaginatedResponse[StockTakeResponse])
async def get_stock_takes(
    location_id: UUID | None = Query(None, description='Filter by location'),
    status_filter: StockTakeStatus | None = Query(None, description='Filter by status'),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[StockTakeResponse]:
    """
    List of all user's inventories.

    Supports filtering by storage location and status.
    """
    org_id = require_org(current_user)
    stock_takes, total = await list_stock_takes_filtered(
        db,
        org_id,
        location_id,
        status_filter,
        offset,
        limit,
    )
    return PaginatedResponse[StockTakeResponse].from_slice(
        [StockTakeResponse.model_validate(st) for st in stock_takes],
        offset=offset,
        limit=limit,
        total=total,
    )


@router.get('/locations', response_model=PaginatedResponse[LocationCountState])
async def get_location_count_states(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[LocationCountState]:
    """When each location was last counted, and which are being counted now.

    Only locations with something to say are listed: one never counted and
    not being counted is absent.
    """
    org_id = require_org(current_user)
    # Only the locations the counts speak of, and those below an open count:
    # the rest have nothing to say, so the organization's locations are not read.
    last_counted = await last_counted_everywhere(db, org_id)
    roots = await open_counts_by_root(db, org_id)
    under_way: dict[UUID, UUID] = dict(roots)
    covered: dict[UUID, StorageDTO] = {}
    for root, stock_take_id in roots.items():
        subtree, _above = await core_api.locations.subtree_and_ancestors_async(
            db, org_id, root
        )
        for storage in subtree:
            covered[storage.id] = storage
            under_way.setdefault(storage.id, stock_take_id)
    named = {
        storage.id: storage
        for storage in await core_api.locations.list_by_ids_async(
            db, org_id, last_counted.keys() - covered.keys()
        )
    }
    storages = sorted([*named.values(), *covered.values()], key=lambda s: s.name)
    states = [
        LocationCountState(
            location_id=storage.id,
            last_counted_at=last_counted.get(storage.id),
            stock_take_id=under_way.get(storage.id),
        )
        for storage in storages
        if storage.id in last_counted or storage.id in under_way
    ]
    return PaginatedResponse.from_full_list(states, offset=offset, limit=limit)


@router.get('/{stock_take_id}', response_model=StockTakeWithDetails)
async def get_stock_take(
    stock_take_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeWithDetails:
    """Fetches inventory details with items."""
    stock_take, storage_dto = await get_stock_take_or_404(
        stock_take_id, current_user, db, with_storage=True
    )

    items = await get_stock_take_items_simple(db, stock_take_id)
    summary = await calculate_stock_take_summary(stock_take_id, db)

    response = StockTakeWithDetails.model_validate(stock_take)
    response.location_name = storage_dto.name if storage_dto else None
    response.location_type_name = (
        storage_dto.location_type.name
        if storage_dto and storage_dto.location_type
        else None
    )
    response.items_count = summary['items_count']
    response.counted_items_count = summary['counted_items_count']
    response.discrepancies_count = summary['discrepancies_count']
    response.progress_percent = summary['progress_percent']
    response.items = [StockTakeItemWithDetails.model_validate(i) for i in items]
    tree_ids, _family_ids, paths = await get_storage_tree(
        db, stock_take.organization_id, stock_take.storage_location_id
    )
    counted_locations = sorted(
        (
            CountedLocation(id=location_id, path=paths[location_id])
            for location_id in tree_ids
        ),
        key=lambda location: location.path,
    )
    return response.model_copy(
        update={
            'counted_locations': counted_locations,
            'closed_locations': await list_closed_locations(db, stock_take_id),
        }
    )


@router.put('/{stock_take_id}', response_model=StockTakeResponse)
async def update_stock_take(
    stock_take_id: UUID,
    stock_take_in: StockTakeUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeResponse:
    """Updates inventory (name, description, notes)."""
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    if stock_take.status not in [StockTakeStatus.DRAFT, StockTakeStatus.IN_PROGRESS]:
        raise catalogue_refusal('stock_take_edit_completed')
    stock_take = await update_stock_take_fields(
        db, stock_take, stock_take_in, user_id=current_user.id
    )
    summary = await calculate_stock_take_summary(stock_take.id, db)
    return StockTakeResponse.model_validate(stock_take).model_copy(
        update={
            'items_count': summary['items_count'],
            'counted_items_count': summary['counted_items_count'],
            'discrepancies_count': summary['discrepancies_count'],
        }
    )


@router.patch('/{stock_take_id}/status', response_model=StockTakeResponse)
async def update_stock_take_status(
    stock_take_id: UUID,
    status_update: StockTakeStatusUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeResponse:
    """Changes inventory status."""
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    stock_take = await update_stock_take_status_service(
        db, stock_take, status_update, user_id=current_user.id
    )
    summary = await calculate_stock_take_summary(stock_take.id, db)
    return StockTakeResponse.model_validate(stock_take).model_copy(
        update={
            'items_count': summary['items_count'],
            'counted_items_count': summary['counted_items_count'],
            'discrepancies_count': summary['discrepancies_count'],
        }
    )


@router.delete('/{stock_take_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_stock_take(
    stock_take_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    """Deletes inventory (only DRAFT or IN_PROGRESS)."""
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    if stock_take.status not in [StockTakeStatus.DRAFT, StockTakeStatus.IN_PROGRESS]:
        raise catalogue_refusal('stock_take_delete_completed')

    await delete_stock_take_entity(db, stock_take, user_id=current_user.id)
    return None


@router.get(
    '/{stock_take_id}/items',
    response_model=PaginatedResponse[StockTakeItemResponse],
)
async def get_stock_take_items(
    stock_take_id: UUID,
    include_counted: bool | None = Query(None, description='Only counted'),
    include_discrepancies: bool | None = Query(
        None, description='Only with discrepancies'
    ),
    search: str | None = Query(None, description='Search by name'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Fetches inventory items."""
    await get_stock_take_or_404(stock_take_id, current_user, db)
    items, total = await get_stock_take_items_filtered(
        db,
        stock_take_id,
        include_counted,
        include_discrepancies,
        search,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse.from_slice(items, offset=offset, limit=limit, total=total)


@router.post(
    '/{stock_take_id}/items',
    response_model=StockTakeItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_surplus_stock_take_item(
    stock_take_id: UUID,
    item_data: StockTakeItemCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeItem:
    """Add a surplus item to a stock take.

    Used when an item is found during counting that was not in the original list.
    The item must exist in the organization.
    """
    lang = get_current_lang()
    org_id = require_org(current_user)
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    if stock_take.status != StockTakeStatus.IN_PROGRESS:
        raise catalogue_refusal('stock_take_not_active')

    if item_data.item_id is None:
        raise AppException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code='VALIDATION_ERROR',
            message=get_error_message('stock_take_surplus_item_id_required', lang),
            field='item_id',
        )

    if item_data.counted_quantity is None:
        raise AppException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code='VALIDATION_ERROR',
            message=get_error_message('stock_take_surplus_quantity_required', lang),
            field='counted_quantity',
        )

    return await add_surplus_item(
        db=db,
        stock_take_id=stock_take_id,
        org_id=org_id,
        item_id=item_data.item_id,
        counted_quantity=item_data.counted_quantity,
        notes=item_data.notes,
        user_id=current_user.id,
        storage_location_id=item_data.location_id,
    )


@router.patch(
    '/{stock_take_id}/items/{item_id}/count', response_model=StockTakeItemResponse
)
async def count_stock_take_item(
    stock_take_id: UUID,
    item_id: UUID,
    count_data: StockTakeItemCountUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeItem:
    """Saves counted quantity for single item."""
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    if stock_take.status != StockTakeStatus.IN_PROGRESS:
        raise catalogue_refusal('stock_take_not_active')

    stock_take_item = await get_stock_take_item_or_404(
        db, stock_take_id, item_id, org_id=current_user.organization_id
    )
    return await count_item_and_commit(
        db,
        stock_take_item,
        count_data,
        tolerance_percent=stock_take.tolerance_percent,
        user_id=current_user.id,
        organization_id=stock_take.organization_id,
        stock_take_name=stock_take.name,
    )


@router.post(
    '/{stock_take_id}/locations/{location_id}/close', response_model=ShelfClosed
)
async def close_stock_take_location(
    stock_take_id: UUID,
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShelfClosed:
    """Close one shelf of the count: what nobody counted on it is counted as 0.

    A shelf with nothing on it is confirmed as empty. Shelves nobody closed
    keep their uncounted rows waiting.
    """
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    if stock_take.status != StockTakeStatus.IN_PROGRESS:
        raise catalogue_refusal('stock_take_not_active')

    return await close_location(db, stock_take, location_id, current_user.id)


@router.post(
    '/{stock_take_id}/items/{item_id}/recount', response_model=StockTakeItemResponse
)
async def request_recount(
    stock_take_id: UUID,
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeItem:
    """Send one row back to be counted again.

    The first answer to a difference nobody expected is to count it a second
    time, not to approve it — that is what SAP's recount document and the
    second recording on a Dynamics inventory order are for, and what a WMS
    does on its own once a variance crosses its threshold. The count stays
    open, the number already recorded stays where it is, and the row will not
    post until somebody has looked again.
    """
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    if stock_take.status != StockTakeStatus.IN_PROGRESS:
        raise catalogue_refusal('stock_take_not_active')

    stock_take_item = await get_stock_take_item_or_404(
        db, stock_take_id, item_id, org_id=current_user.organization_id
    )
    stock_take_item.recount_requested = True
    # A recount is a doubt somebody raised about a recorded number —
    # exactly what the log exists to keep.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=stock_take.organization_id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take_id,
        snapshot={
            'name': stock_take.name,
            'item_name': stock_take_item.item_name,
            'item_id': str(item_id),
            'recount_requested': True,
        },
    )
    await db.commit()
    await db.refresh(stock_take_item)
    return stock_take_item


@router.patch(
    '/{stock_take_id}/items/bulk-count',
    # list-envelope-exception: a bulk result, the items this request just counted
    response_model=list[StockTakeItemResponse],
)
@map_service_errors
async def bulk_count_stock_take_items(
    stock_take_id: UUID,
    items_update: list[StockTakeItemCountUpdate],
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> list[StockTakeItem]:
    """Bulk counting of inventory items."""
    stock_take = await get_stock_take_or_404(stock_take_id, current_user, db)

    if stock_take.status != StockTakeStatus.IN_PROGRESS:
        raise catalogue_refusal('stock_take_not_active')

    return await bulk_count_items_and_commit(
        db,
        stock_take_id,
        items_update,
        tolerance_percent=stock_take.tolerance_percent,
        user_id=current_user.id,
        organization_id=stock_take.organization_id,
        stock_take_name=stock_take.name,
    )


@router.post('/{stock_take_id}/complete', response_model=StockTakeReport)
@map_service_errors
async def complete_stock_take(
    stock_take_id: UUID,
    complete_data: StockTakeComplete,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeReport | JSONResponse:
    """Finalizes inventory and optionally applies corrections."""
    org_id = require_org(current_user)
    # Accepting a difference the organization's own tolerance calls too large
    # is the one decision on this screen that is not the counter's to make.
    # Checked here rather than in the service: who somebody is belongs to the
    # request, and the service already has enough to answer for.
    #
    # The growth cap is the larger claim of the two — a count many times the
    # system quantity — and it asked for nothing beyond the permission to
    # count, while its neighbour asked for this one.
    accepting = complete_data.force_over_tolerance or complete_data.force_over_cap
    if accepting and not current_user.has_permission('stock_takes:approve'):
        raise catalogue_status_refusal(
            'stock_take_tolerance_not_allowed', status.HTTP_403_FORBIDDEN
        )
    stock_take, storage_dto = await get_stock_take_or_404(
        stock_take_id, current_user, db, with_storage=True
    )
    try:
        return await finalize_stock_take(
            db, stock_take, complete_data, org_id, current_user.id, storage_dto
        )
    except ConflictException as refusal:
        detail = refusal.detail
        if isinstance(detail, dict) and detail.get('code') == 'STOCK_TAKE_STOCK_MOVED':
            # The refusal's whole point is the rows it sent back to be
            # counted again. Raising would roll them back with the rest, so
            # the 409 is returned instead and the session commits as for any
            # answer; the body is the one the raise would have produced.
            return JSONResponse(
                status_code=refusal.status_code, content={'detail': detail}
            )
        raise


@router.get('/{stock_take_id}/report', response_model=StockTakeReport)
async def get_stock_take_report(
    stock_take_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StockTakeReport:
    """Fetches inventory report."""
    stock_take, storage_dto = await get_stock_take_or_404(
        stock_take_id, current_user, db, with_storage=True
    )
    return await build_stock_take_report(db, stock_take, storage_dto)
