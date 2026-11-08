from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.datetimes import parse_iso_date
from app.core.deps import require_org
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import ServiceRejectionError, catalogue_refusal
from app.core.logging import get_logger
from app.core.scan_providers import LABEL_CODE_PATTERN
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.label_pool import LabelPool
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.schemas.label_pool import LabelAssignRequest
from app.services.items._quota import check_item_quota_async
from app.services.items._stock_quant import (
    apply_quantity_change_async,
    lock_record_stock_async,
)
from app.services.items.history import log_history_async

logger = get_logger(__name__)

_LABEL_PATTERN = LABEL_CODE_PATTERN
_BARCODE_PATTERN = re.compile(r'^\d{8,14}$')


async def _resolve_short_code(
    db: AsyncSession, short_code: str, org_id: UUID
) -> tuple[LabelPool | None, str | None]:
    """Classify ``short_code`` as a label (locked for update) or a numeric barcode.

    Returns (label, None) for a label code, (None, barcode) for a barcode,
    or raises ValueError for any other format.
    """
    if _LABEL_PATTERN.match(short_code):
        label = (
            await db.scalars(
                select(LabelPool)
                .where(
                    LabelPool.short_code == short_code,
                    LabelPool.organization_id == org_id,
                )
                .with_for_update()
            )
        ).first()
        if not label:
            raise ServiceRejectionError('label_not_found')
        if label.is_assigned:
            raise ServiceRejectionError('label_already_assigned')
        return label, None
    if _BARCODE_PATTERN.match(short_code):
        return None, short_code
    raise ServiceRejectionError('short_code_invalid_format')


async def _validate_storage_location(
    db: AsyncSession, storage_id: UUID, org_id: UUID
) -> None:
    """Raise ValueError when the storage location is missing or not in this org,
    and refuse an archived one.

    The archived gate is the manual create's own rule (it refuses with the
    same translated message): an archived shelf is off every picker, and a
    scan must not reopen it as a back door. The tenancy miss keeps this
    endpoint's 400 rather than the manual path's 404 — the scan code in the
    URL is already the secret being presented, so the response gains
    nothing by playing coy about the location.
    """
    location = (
        await db.scalars(
            select(StorageLocation).where(
                StorageLocation.id == storage_id,
                StorageLocation.organization_id == org_id,
            )
        )
    ).first()
    if not location:
        raise ServiceRejectionError('storage_not_found')
    if (location.settings or {}).get('archived') is True:
        raise catalogue_refusal('storage_archived')


def _parse_iso_date(value: str | None, field: str) -> date | None:
    """Shared ISO parsing, plus the debug line that says which field was bad."""
    parsed = parse_iso_date(value)
    if value and parsed is None:
        logger.debug('Invalid %s format: %s', field, value)
    return parsed


async def _find_existing_item_by_barcode(
    db: AsyncSession,
    barcode: str,
    data: LabelAssignRequest,
    expiry_date_obj: date | None,
) -> Item | None:
    """Return the existing non-deleted item matching (code, location, expiry) — if any.

    The code a scan carries lives on the product's catalogue row while the
    record stays bare (``_product_code`` owns that decision), so asking
    ``Item.barcode`` alone missed the very record a rescan should bump and
    minted a duplicate instead. Both carriers are asked, the same or_ the
    typed search asks (_search_terms).

    The order is the increment target, and it has three keys: the row
    wearing the *scanned* code first, then the bare rows — the ones a scan
    creates — and a row wearing some other code of the same product only
    after both; ``created_at`` decides what is left, so repeated scans of
    one code keep bumping one record instead of drifting with page order.
    Asking "wears a code" instead of "wears this code" put a rescan of one
    code onto a row wearing another, and an order with no tiebreaker moved
    the target between rows from one request to the next.
    """
    return (
        await db.scalars(
            select(Item)
            .where(
                Item.storage_location_id == data.location_id,
                Item.expiry_date == expiry_date_obj,
                Item.is_deleted.is_(False),
                or_(
                    Item.barcode == barcode,
                    Item.template.has(ProductTemplate.barcode == barcode),
                ),
            )
            .order_by(
                Item.barcode.is_distinct_from(barcode),
                Item.barcode.isnot(None),
                Item.created_at,
            )
        )
    ).first()


async def _increment_existing_item(
    db: AsyncSession,
    item: Item,
    data: LabelAssignRequest,
    current_user: UserContextDTO,
    org_id: UUID,
    barcode: str,
) -> None:
    """Bump quantity on a pre-existing item, write history, emit ITEM_UPDATED."""
    from app.core.period_guard import check_period_not_closed
    from app.services.analytics._common import org_today_async
    from app.services.uom_service import validate_quantity_precision_async

    # Block inventory increments via barcode scan when the current
    # period is closed — closed by the organization's own day, not the
    # server's. Creating a new item (no existing row) is NOT
    # blocked — see _create_new_item; only mutations to existing stock
    # fall under the period lock.
    if item.organization_id is not None:
        await check_period_not_closed(
            db,
            item.organization_id,
            await org_today_async(db, item.organization_id),
        )

    # The rescan is one more door that takes a number a person named, and
    # the unit it lands in is the record's: the same gate as a new record.
    if item.uom_id is not None:
        await validate_quantity_precision_async(
            db, item.uom_id, Decimal(str(data.quantity)), org_id
        )

    # The bump is worked out from the record's number, so that number is
    # read under the lock, not from the lookup that found the record.
    await lock_record_stock_async(db, item)
    old_qty = item.quantity
    await apply_quantity_change_async(
        db,
        item,
        item.quantity + Decimal(str(data.quantity)),
        old_quantity=old_qty,
        user_id=current_user.id,
    )
    await log_history_async(
        db,
        item,
        ItemAction.QUANTITY_INCREASED_VIA_SCAN,
        {
            'barcode': barcode,
            # The exact digits, as every quantity in the history (AUDIT.md).
            'old_quantity': str(old_qty),
            'new_quantity': str(item.quantity),
            'increment': str(Decimal(str(data.quantity))),
        },
        user_id=current_user.id,
    )
    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_UPDATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(org_id),
                'item': item,
                'changes': {
                    'quantity': float(item.quantity),
                    'via_scan_increment': True,
                },
                'user_id': str(current_user.id),
            }
        ),
    )


async def _create_new_item(
    db: AsyncSession,
    data: LabelAssignRequest,
    label: LabelPool | None,
    barcode: str | None,
    expiry_date_obj: date | None,
    freeze_date_obj: date | None,
    current_user: UserContextDTO,
) -> Item:
    """Create a new item from the scan, through the door the form uses.

    A scan is one more door into the same warehouse. It used to hold a
    second copy of the create sequence — same guards, hand-wired in a
    different order — and every rule added to one door was a rule the other
    did not have: the unit-vs-template confirmation never reached this side
    at all. What stays here is what is genuinely scan-shaped: which label
    the record is born wearing, and how its birth reads in the history.
    """
    from app.schemas.item import ItemCreate
    from app.services.items._create import create_item_async

    item_in = ItemCreate(
        location_id=data.location_id,
        category_id=data.category_id,
        name=data.name,
        brand=data.brand,
        description=data.description,
        # The request carries a float; stock arithmetic downstream is Decimal
        # and refuses to mix the two.
        quantity=Decimal(str(data.quantity)),
        uom_id=data.uom_id,
        # Passed through for template resolution, not stored on the item.
        weight_value=data.weight_value,
        weight_uom_id=data.weight_uom_id,
        expiry_date=expiry_date_obj,
        freeze_date=freeze_date_obj,
        image_url=data.image_url,
        metadata=data.metadata,
        serial_number=(data.serial_number or '').strip() or None,
        purchase_price=data.purchase_price,
        shelf_location=data.shelf_location,
        barcode=barcode,
        unit_confirmed_over_template=data.unit_confirmed_over_template,
    )
    item = await create_item_async(
        db,
        item_in,
        current_user,
        history_action=ItemAction.CREATED_VIA_SCAN,
        history_changes={
            'label_code': label.short_code if label else None,
            'barcode': barcode,
            'via_vision_ai': bool(data.metadata),
        },
        label_code=label.short_code if label else None,
    )

    if label:
        label.is_assigned = True
        label.item_id = item.id
        label.assigned_at = datetime.now(UTC)

    return item


async def assign_label_or_barcode(
    db: AsyncSession,
    short_code: str,
    data: LabelAssignRequest,
    current_user: UserContextDTO,
) -> Item:
    """Assign a label to a newly created item OR create/update an item with a barcode."""
    org_id = require_org(current_user)

    label, barcode = await _resolve_short_code(db, short_code, org_id)
    await _validate_storage_location(db, data.location_id, org_id)
    await check_item_quota_async(org_id, db)

    expiry_date_obj = _parse_iso_date(data.expiry_date, 'expiry_date')
    freeze_date_obj = _parse_iso_date(data.freeze_date, 'freeze_date')

    existing_item: Item | None = None
    if barcode:
        existing_item = await _find_existing_item_by_barcode(
            db, barcode, data, expiry_date_obj
        )

    if existing_item:
        assert (
            barcode is not None
        )  # narrowing: existing_item only set when barcode is truthy
        await _increment_existing_item(
            db, existing_item, data, current_user, org_id, barcode
        )
        item = existing_item
    else:
        # A pool label is no product code, so the form asks for one; a
        # scanned barcode is the code, and the form does not ask again.
        item = await _create_new_item(
            db,
            data,
            label,
            barcode or data.barcode,
            expiry_date_obj,
            freeze_date_obj,
            current_user,
        )

    # Flush only — the router owns the transaction (get_async_db commits on
    # endpoint success / rolls back on error). A service-level commit here
    # would prevent the caller from rolling back on a later failure.
    await db.flush()
    # `template` joins the eager-loaded set: the response serialises
    # `min_quantity`, which reads it, and a lazy load there fails outside the
    # greenlet.
    await db.refresh(item, ['category', 'uom', 'template'])

    return item
