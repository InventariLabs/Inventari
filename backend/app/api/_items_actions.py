from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_user_storage_ids
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_permission,
)
from app.core.exceptions import (
    ConflictException,
    PeriodClosedError,  # inventory period lock mapping
    ServiceRejectionError,
    map_service_errors,
)
from app.core.public_api import core_api
from app.schemas.item import (
    Item as ItemSchema,
)
from app.schemas.item import (
    ItemConsumeRequest,
    ItemDiscardRequest,
    ItemMove,
    ItemQuantityUpdate,
    ItemUseByRequest,
    ItemUsePartiallyRequest,
)
from app.services.items import (
    consume_item as consume_item_service,
)
from app.services.items import (
    discard_item as discard_item_service,
)
from app.services.items import (
    move_item as move_item_service,
)
from app.services.items import (
    update_quantity,
)
from app.services.items._open_package import set_use_by_async, use_partially_async
from app.services.items._query_special import get_item_or_404_async

router = APIRouter()


@router.patch('/{item_id}/quantity', response_model=ItemSchema)
async def update_item_quantity(
    item_id: UUID,
    quantity_update: ItemQuantityUpdate,
    source_document_id: UUID | None = Query(None),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Change product quantity."""
    item = await get_item_or_404_async(db, item_id, user_storage_ids)
    # A used-up record stands in the virtual Consumed place, where stock is
    # not counted. "+1 unit" on its row sends the stored figure plus one
    # through here, and the unit would land in that place: a record with a
    # quantity that no list, search or counter shows. Raising it is refused
    # with the place named; lowering it, or anything on a real shelf, passes.
    if quantity_update.quantity > item.quantity and current_user.organization_id:
        place = await core_api.locations.get_async(
            db, current_user.organization_id, item.storage_location_id
        )
        # 'internal' is LocationUsage.INTERNAL as the CoreAPI DTO spells it:
        # the virtual counterparts (consumed, loss, production) are where a
        # raise would book stock nobody counts.
        if place is not None and place.usage != 'internal':
            raise ServiceRejectionError(
                'item_quantity_raise_in_virtual_location', location=place.name
            )
    # The unit says the smallest step it is counted in, and a piece says one.
    # Asked here rather than in the service, for the same reason the stock
    # take asks who somebody is at its own door: this is a rule about a
    # number a person typed. Inside, a conversion may legitimately produce a
    # fraction of a piece — the recipes bridge takes half a packet when half
    # a packet's weight is what the scan says left the shelf.
    if item.uom_id is not None:
        await core_api.uoms.validate_quantity_precision_async(
            db,
            item.uom_id,
            quantity_update.quantity_as_named or quantity_update.quantity,
            item.organization_id,
        )
    try:
        return await update_quantity(
            db=db,
            item=item,
            quantity_update=quantity_update,
            user_id=current_user.id,
            source_document_id=source_document_id,
        )
    except PeriodClosedError as exc:
        raise ConflictException('PERIOD_CLOSED', str(exc)) from exc


@router.patch('/{item_id}/move', response_model=ItemSchema)
@map_service_errors
async def move_item(
    item_id: UUID,
    move_data: ItemMove,
    source_document_id: UUID | None = Query(None),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Move product to another storage location."""
    item = await get_item_or_404_async(db, item_id, user_storage_ids)
    return await move_item_service(
        db=db,
        item=item,
        move_data=move_data,
        user=current_user,
        source_document_id=source_document_id,
    )


@router.patch('/{item_id}/consume', response_model=ItemSchema)
@map_service_errors
async def consume_item(
    item_id: UUID,
    consume_data: ItemConsumeRequest,
    source_document_id: UUID | None = Query(None),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Consume product (eaten, used)."""
    item = await get_item_or_404_async(db, item_id, user_storage_ids)
    # The same door the quantity endpoint keeps: a number a person typed is
    # asked against the unit's smallest step here, while the service stays
    # open to the conversions inside that may legitimately produce a fraction.
    if item.uom_id is not None:
        await core_api.uoms.validate_quantity_precision_async(
            db, item.uom_id, consume_data.quantity, item.organization_id
        )
    return await consume_item_service(
        db=db,
        item=item,
        consume_data=consume_data,
        user=current_user,
        source_document_id=source_document_id,
    )


@router.post('/{item_id}/use-partially', response_model=ItemSchema)
@map_service_errors
async def use_item_partially(
    item_id: UUID,
    use_data: ItemUsePartiallyRequest,
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Open a package, or say how much of an open one is left.

    Answers with the record that is now the open package: the same one when
    it held a single unit, a new one split off when it held several.
    """
    item = await get_item_or_404_async(db, item_id, user_storage_ids)
    return await use_partially_async(
        db,
        item,
        current_user,
        left=use_data.left,
        left_uom_id=use_data.left_uom_id,
        use_by=use_data.use_by,
        set_use_by='use_by' in use_data.model_fields_set,
    )


@router.put('/{item_id}/use-by', response_model=ItemSchema)
@map_service_errors
async def set_item_use_by(
    item_id: UUID,
    use_by_data: ItemUseByRequest,
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Edit, or with ``null`` clear, the use-by of an opened package."""
    item = await get_item_or_404_async(db, item_id, user_storage_ids)
    return await set_use_by_async(db, item, current_user, use_by_data.use_by)


@router.patch('/{item_id}/discard', response_model=ItemSchema)
@map_service_errors
async def discard_item(
    item_id: UUID,
    discard_data: ItemDiscardRequest,
    source_document_id: UUID | None = Query(None),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Discard product (expired, damaged, lost)."""
    item = await get_item_or_404_async(db, item_id, user_storage_ids)
    if item.uom_id is not None:
        await core_api.uoms.validate_quantity_precision_async(
            db, item.uom_id, discard_data.quantity, item.organization_id
        )
    return await discard_item_service(
        db=db,
        item=item,
        discard_data=discard_data,
        user=current_user,
        source_document_id=source_document_id,
    )
