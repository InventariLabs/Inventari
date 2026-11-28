"""HTTP surface of the rentals module.

Every endpoint resolves the organization first and is mounted on a router
gated by the module and its read/write permissions, so an endpoint added
later is covered by the same gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.module_sdk import (
    ConflictException,
    PaginatedResponse,
    ServiceRejectionError,
    get_async_db,
    get_current_lang,
    get_current_user_context,
    get_error_message,
    require_module,
    require_org,
    require_read_write,
)
from app.core.public_api import core_api
from app.modules.equipment.equipment_api import EquipmentAssetDTO, equipment_api

from . import _documents, _kits, service
from ._availability import (
    check_line,
    load_world,
    model_pool,
    nearest_window,
)
from ._blocks import (
    create_block,
    delete_block,
    delete_buffer_rule,
    list_blocks,
    list_buffer_rules,
    set_buffer_rule,
    update_block,
)
from .exceptions import RentalConflictError
from .schemas import (
    AssetOption,
    BlockCreate,
    BlockSchema,
    BlockUpdate,
    BookingCheckRequest,
    BookingCheckResponse,
    BookingCreate,
    BookingListRow,
    BookingSchema,
    BufferRuleIn,
    BufferRuleSchema,
    BusyInterval,
    CalendarResponse,
    CategoryOption,
    ExtendRequest,
    KitCreate,
    KitListRow,
    KitSchema,
    KitUpdate,
    ModelOption,
    NearestWindowResponse,
    PickupRequest,
    RentalAvailabilityResponse,
    ReturnRequest,
    TodayResponse,
)

router = APIRouter(
    dependencies=[
        Depends(require_module('rentals')),
        require_read_write('rentals:read', 'rentals:write'),
    ]
)


def _conflict(exc: RentalConflictError) -> ConflictException:
    return ConflictException(
        exc.code,
        get_error_message(exc.key, get_current_lang(), **exc.kwargs),
        details=exc.details,
    )


@router.get('/today', response_model=TodayResponse)
async def today_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> TodayResponse:
    return await service.today_view(db, org_id)


@router.get('/calendar', response_model=CalendarResponse)
async def calendar_endpoint(
    starts_at: datetime = Query(...),
    ends_at: datetime = Query(...),
    model: str | None = Query(None),
    category_id: UUID | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> CalendarResponse:
    return await service.calendar_view(
        db, org_id, starts_at, ends_at, model=model, category_id=category_id
    )


@router.get('/bookings', response_model=PaginatedResponse[BookingListRow])
async def list_bookings_endpoint(
    status_filter: str | None = Query(None, alias='status'),
    search: str | None = Query(None, max_length=200),
    partner_id: UUID | None = Query(None),
    item_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[BookingListRow]:
    bookings, total = await service.list_bookings(
        db,
        org_id,
        status=status_filter,
        search=search,
        partner_id=partner_id,
        item_id=item_id,
        limit=limit,
        offset=offset,
    )
    rows = await service.booking_rows(db, org_id, bookings)
    return PaginatedResponse[BookingListRow].from_slice(rows, offset, limit, total)


@router.post(
    '/bookings', response_model=BookingSchema, status_code=status.HTTP_201_CREATED
)
async def create_booking_endpoint(
    data: BookingCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BookingSchema:
    try:
        booking = await service.create_booking(db, org_id, data, current_user.id)
    except RentalConflictError as exc:
        raise _conflict(exc) from exc
    assets = await equipment_api.list_bookable_assets_async(
        db, org_id, include_retired=True
    )
    return await service.booking_schema(
        db, booking, {asset.id: asset for asset in assets}
    )


@router.post('/bookings/check', response_model=BookingCheckResponse)
async def check_booking_endpoint(
    data: BookingCheckRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BookingCheckResponse:
    return await service.check_booking(db, org_id, data)


@router.get('/bookings/{booking_id}', response_model=BookingSchema)
async def get_booking_endpoint(
    booking_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BookingSchema:
    booking = await service._require_booking(db, org_id, booking_id)
    return await service.booking_schema(db, booking)


@router.post('/bookings/{booking_id}/cancel', response_model=BookingSchema)
async def cancel_booking_endpoint(
    booking_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BookingSchema:
    await service.cancel_booking(db, org_id, booking_id, current_user.id)
    booking = await service._require_booking(db, org_id, booking_id)
    return await service.booking_schema(db, booking)


@router.post('/bookings/{booking_id}/pickup', response_model=BookingSchema)
async def pickup_booking_endpoint(
    booking_id: UUID,
    data: PickupRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BookingSchema:
    try:
        await service.pickup_booking(db, org_id, booking_id, data, current_user.id)
    except RentalConflictError as exc:
        raise _conflict(exc) from exc
    booking = await service._require_booking(db, org_id, booking_id)
    return await service.booking_schema(db, booking)


@router.post('/bookings/{booking_id}/return', response_model=BookingSchema)
async def return_booking_endpoint(
    booking_id: UUID,
    data: ReturnRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BookingSchema:
    try:
        await service.return_booking(db, org_id, booking_id, data, current_user.id)
    except RentalConflictError as exc:
        raise _conflict(exc) from exc
    booking = await service._require_booking(db, org_id, booking_id)
    return await service.booking_schema(db, booking)


@router.post('/bookings/{booking_id}/extend', response_model=BookingSchema)
async def extend_booking_endpoint(
    booking_id: UUID,
    data: ExtendRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BookingSchema:
    try:
        await service.extend_booking(db, org_id, booking_id, data, current_user.id)
    except RentalConflictError as exc:
        raise _conflict(exc) from exc
    booking = await service._require_booking(db, org_id, booking_id)
    return await service.booking_schema(db, booking)


@router.get(
    '/kits',
    # list-envelope-exception: a vocabulary of reusable sets, the booking sheet searches it
    response_model=list[KitListRow],
)
async def list_kits_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[KitListRow]:
    return await _kits.list_kits(db, org_id)


@router.post('/kits', response_model=KitSchema, status_code=status.HTTP_201_CREATED)
async def create_kit_endpoint(
    data: KitCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> KitSchema:
    return await _kits.create_kit(db, org_id, data, current_user.id)


@router.get('/kits/{kit_id}', response_model=KitSchema)
async def get_kit_endpoint(
    kit_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> KitSchema:
    return await _kits.kit_schema_by_id(db, org_id, kit_id)


@router.put('/kits/{kit_id}', response_model=KitSchema)
async def update_kit_endpoint(
    kit_id: UUID,
    data: KitUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> KitSchema:
    return await _kits.update_kit(db, org_id, kit_id, data, current_user.id)


@router.delete('/kits/{kit_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_kit_endpoint(
    kit_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    await _kits.delete_kit(db, org_id, kit_id, current_user.id)


def _pdf_response(pdf: bytes, filename: str) -> Response:
    return Response(
        content=pdf,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}.pdf"'},
    )


@router.get('/bookings/{booking_id}/pick-list')
async def pick_list_endpoint(
    booking_id: UUID,
    lang: str = Query('en', max_length=8),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    booking = await service._require_booking(db, org_id, booking_id)
    pdf = await _documents.render_document_pdf(
        db, org_id, booking, _documents.DOCUMENT_PICK_LIST, lang
    )
    return _pdf_response(pdf, f'pick-list-{str(booking.id)[:8]}')


@router.get('/bookings/{booking_id}/handover-sheet')
async def handover_sheet_endpoint(
    booking_id: UUID,
    lang: str = Query('en', max_length=8),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    booking = await service._require_booking(db, org_id, booking_id)
    pdf = await _documents.render_document_pdf(
        db, org_id, booking, _documents.DOCUMENT_HANDOVER, lang
    )
    return _pdf_response(pdf, f'handover-{str(booking.id)[:8]}')


@router.get('/blocks', response_model=PaginatedResponse[BlockSchema])
async def list_blocks_endpoint(
    item_id: UUID | None = Query(None),
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[BlockSchema]:
    blocks, total = await list_blocks(
        db,
        org_id,
        item_id=item_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse[BlockSchema].from_slice(blocks, offset, limit, total)


@router.post('/blocks', response_model=BlockSchema, status_code=status.HTTP_201_CREATED)
async def create_block_endpoint(
    data: BlockCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BlockSchema:
    try:
        return await create_block(db, org_id, data, current_user.id)
    except RentalConflictError as exc:
        raise _conflict(exc) from exc


@router.patch('/blocks/{block_id}', response_model=BlockSchema)
async def update_block_endpoint(
    block_id: UUID,
    data: BlockUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BlockSchema:
    try:
        return await update_block(db, org_id, block_id, data, current_user.id)
    except RentalConflictError as exc:
        raise _conflict(exc) from exc


@router.delete('/blocks/{block_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_block_endpoint(
    block_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    await delete_block(db, org_id, block_id, current_user.id)


@router.get(
    '/buffer-rules',
    # list-envelope-exception: a vocabulary, one rule per model or category
    response_model=list[BufferRuleSchema],
)
async def list_buffer_rules_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[BufferRuleSchema]:
    return await list_buffer_rules(db, org_id)


@router.put('/buffer-rules', response_model=BufferRuleSchema)
async def set_buffer_rule_endpoint(
    data: BufferRuleIn,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BufferRuleSchema:
    return await set_buffer_rule(db, org_id, data, current_user.id)


@router.delete('/buffer-rules/{rule_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_buffer_rule_endpoint(
    rule_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    await delete_buffer_rule(db, org_id, rule_id, current_user.id)


@router.get(
    '/assets',
    # list-envelope-exception: the organization's bookable fleet, a reference list the pickers search
    response_model=list[AssetOption],
)
async def list_assets_endpoint(
    search: str | None = Query(None, max_length=200),
    category_id: UUID | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[AssetOption]:
    assets = await equipment_api.list_bookable_assets_async(
        db, org_id, search=search, category_id=category_id
    )
    return [_asset_option(asset) for asset in assets]


@router.get(
    '/models',
    # list-envelope-exception: a vocabulary, the models the fleet carries
    response_model=list[ModelOption],
)
async def list_models_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[ModelOption]:
    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    counts: dict[str, int] = {}
    for asset in assets:
        if asset.model:
            counts[asset.model] = counts.get(asset.model, 0) + 1
    return [
        ModelOption(model=model, total_units=count)
        for model, count in sorted(counts.items())
    ]


@router.get('/availability', response_model=RentalAvailabilityResponse)
async def availability_endpoint(
    starts_at: datetime = Query(...),
    ends_at: datetime = Query(...),
    item_id: UUID | None = Query(None),
    model: str | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RentalAvailabilityResponse:
    world = await load_world(db, org_id, starts_at, ends_at, cover_bookings=True)
    if item_id is not None:
        asset = world.assets_by_id.get(item_id)
        if asset is None:
            raise ServiceRejectionError('rental_asset_not_bookable')
        from .schemas import BookingLineIn

        check = check_line(world, BookingLineIn(item_id=item_id), starts_at, ends_at)
        return RentalAvailabilityResponse(
            item_id=item_id,
            model=asset.model,
            starts_at=starts_at,
            ends_at=ends_at,
            total_units=1,
            free_units=check.available,
            busy=[
                BusyInterval(
                    kind=conflict.kind,  # type: ignore[arg-type]
                    starts_at=conflict.starts_at or starts_at,
                    ends_at=conflict.ends_at or ends_at,
                    label=conflict.label,
                    reason=conflict.reason,
                    booking_id=conflict.booking_id,
                )
                for conflict in check.conflicts
            ],
        )
    if model is None:
        raise ServiceRejectionError('rental_availability_needs_target')
    pool = model_pool(world, model, starts_at, ends_at)
    busy: list[BusyInterval] = []
    for _unit, slots in pool.busy:
        for slot in slots:
            busy.append(
                BusyInterval(
                    kind=slot.kind,  # type: ignore[arg-type]
                    starts_at=slot.starts_at,
                    ends_at=slot.ends_at,
                    label=slot.label,
                    reason=slot.reason,
                    booking_id=slot.booking_id,
                )
            )
    return RentalAvailabilityResponse(
        model=model,
        starts_at=starts_at,
        ends_at=ends_at,
        total_units=len(pool.units),
        free_units=pool.free,
        busy=busy,
    )


@router.get('/availability/nearest', response_model=NearestWindowResponse)
async def nearest_window_endpoint(
    starts_at: datetime = Query(...),
    ends_at: datetime = Query(...),
    item_id: UUID | None = Query(None),
    model: str | None = Query(None),
    quantity: int = Query(1, ge=1, le=999),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> NearestWindowResponse:
    from .schemas import BookingLineIn

    if (item_id is None) == (model is None):
        raise ServiceRejectionError('rental_availability_needs_target')
    line = (
        BookingLineIn(item_id=item_id)
        if item_id is not None
        else BookingLineIn(model=model, quantity=quantity)
    )
    world = await load_world(
        db, org_id, starts_at, ends_at + timedelta(days=60), cover_bookings=True
    )
    window = nearest_window(world, line, starts_at, ends_at)
    return NearestWindowResponse(
        starts_at=window.starts_at if window else None,
        ends_at=window.ends_at if window else None,
    )


@router.get(
    '/categories',
    # list-envelope-exception: a vocabulary, the categories a buffer rule can name
    response_model=list[CategoryOption],
)
async def list_categories_endpoint(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[CategoryOption]:
    # Only the categories the bookable fleet is filed under: a calendar filter
    # or a buffer rule has nothing to say about a food category.
    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    in_use = {asset.category_id for asset in assets if asset.category_id is not None}
    categories = await core_api.categories.list_async(db, org_id)
    return [
        CategoryOption(id=category.id, code=category.code, name=category.name)
        for category in categories
        if category.id in in_use
    ]


def _asset_option(asset: EquipmentAssetDTO) -> AssetOption:
    return AssetOption(
        id=asset.id,
        name=asset.name,
        model=asset.model,
        category_id=asset.category_id,
        category_code=asset.category_code,
        category_name=asset.category_name,
        status=asset.status,
        serial_number=asset.serial_number,
        asset_tag=asset.asset_tag,
        barcode=asset.barcode,
    )
