from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemCreateDTO, UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.i18n.service import get_current_lang, get_error_message

from ._serial import without_serial
from .bulk_service import row_error
from .schemas import BulkEquipmentCreate, BulkEquipmentError, BulkEquipmentResponse


async def bulk_create_items(
    db: AsyncSession,
    data: BulkEquipmentCreate,
    user: UserContextDTO,
) -> BulkEquipmentResponse:
    from app.core.public_api import core_api

    created_ids: list[str] = []
    errors: list[BulkEquipmentError] = []
    org_id = user.organization_id
    if org_id is None:
        lang = get_current_lang()
        raise PermissionError(get_error_message('organization_required', lang))

    # Fail fast with a clear per-row error when the target location does not
    # exist — without this check every row would fail with an FK violation.
    if data.location_id:
        loc = await core_api.locations.get_async(db, org_id, data.location_id)
        if not loc:
            no_location = row_error(ServiceRejectionError('storage_not_found'))
            return BulkEquipmentResponse(
                created=0,
                failed=len(data.entries),
                items=[],
                errors=[
                    BulkEquipmentError(
                        index=i, serial_number=e.serial_number, **no_location
                    )
                    for i, e in enumerate(data.entries)
                ],
            )

    incoming_serials = {e.serial_number for e in data.entries if e.serial_number}
    if incoming_serials:
        existing_serials = await core_api.items.list_existing_serials_async(
            db, org_id, incoming_serials
        )
    else:
        existing_serials = set()

    for i, entry in enumerate(data.entries):
        if entry.serial_number and entry.serial_number in existing_serials:
            errors.append(
                BulkEquipmentError(
                    index=i,
                    serial_number=entry.serial_number,
                    **row_error(
                        ServiceRejectionError(
                            'serial_number_exists', serial_number=entry.serial_number
                        )
                    ),
                )
            )
            continue

        equipment_meta: dict[str, Any] = without_serial(
            dict(data.metadata.get('equipment', {}))
        )
        if entry.asset_tag:
            equipment_meta['asset_tag'] = entry.asset_tag

        item_data = ItemCreateDTO(
            name=data.name,
            location_id=data.location_id,
            category_id=data.category_id or None,
            brand=data.brand,
            description=data.description,
            purchase_price=data.purchase_price,
            quantity=Decimal('1'),
            serial_number=entry.serial_number,
            metadata={'equipment': equipment_meta},
        )
        try:
            item = await core_api.items.create_async(
                db=db,
                organization_id=org_id,
                data=item_data,
                user=user,
            )
            created_ids.append(str(item.id))
        except (ValueError, SQLAlchemyError, InvalidOperation) as exc:
            errors.append(
                BulkEquipmentError(
                    index=i,
                    serial_number=entry.serial_number,
                    **row_error(exc),
                )
            )

    return BulkEquipmentResponse(
        created=len(created_ids),
        failed=len(errors),
        items=created_ids,
        errors=errors,
    )
