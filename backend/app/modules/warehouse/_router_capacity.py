"""Putaway capacity CRUD router.

Mounted by ``warehouse/router.py``. Endpoints:
  - GET    /putaway/capacity?location_id=&product_template_id=   list entries
  - POST   /putaway/capacity                                     create an entry
  - PUT    /putaway/capacity/{entry_id}                          change the limit
  - DELETE /putaway/capacity/{entry_id}                          drop the limit
  - GET    /putaway/capacity-settings/{location_id}              read the mix flag
  - PUT    /putaway/capacity-settings/{location_id}              set the mix flag
  - GET    /putaway/receiving-modes                              how warehouses receive
  - PUT    /putaway/receiving-modes/{warehouse_id}               one step or two

Cross-module rule: routers import from CoreAPI for validation
(locations/products) and from the orders module, when it is there, for the
replenishment side of the pair (``_order_side``) — they must NOT import Core
models. A shelf or a product
from another organization is refused with exactly the answer a missing
one gets: existence elsewhere is not ours to confirm.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import ProductTemplateDTO, UserContextDTO
from app.core.db_utils import in_ids
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    NotFoundException,
    ServiceRejectionError,
    map_service_errors,
    refusal_exception,
)
from app.core.module_sdk import (
    PaginatedResponse,
    journal_config_change,
    record_settings,
)
from app.core.public_api import core_api

from ._order_side import order_side_async
from ._receiving_area import list_receiving_modes_async, set_receiving_mode_async
from ._shelf_fill import STATUS_NEARLY_FULL, STATUS_OVER, shelf_fill
from .models import PutawayCapacity, PutawayLocationSetting, WarehouseReceiving
from .putaway_schemas import (
    PutawayCapacityCreate,
    PutawayCapacityOut,
    PutawayCapacityUpdate,
    PutawayLocationSettingOut,
    PutawayLocationSettingUpdate,
    PutawayOccupancyOut,
    WarehouseReceivingOut,
    WarehouseReceivingUpdate,
)

router = APIRouter()


async def _journal_capacity(
    db: AsyncSession,
    current_user: UserContextDTO,
    entry: PutawayCapacity,
    before: Any,
    after: Any,
) -> None:
    """A shelf's limit for a product steers every later delivery: journalled.

    Only the number can move — shelf and product are the limit's identity —
    so they ride beside it on every entry, an edit included, with the names
    they had at the time.
    """
    org_id = require_org(current_user)
    location = await core_api.locations.get_async(db, org_id, entry.location_id)
    template = await core_api.product_templates.get_async(
        db, org_id, entry.product_template_id
    )
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='warehouse',
        subject='putaway-capacity',
        keys={'max_quantity'},
        before=before,
        after=after,
        context={
            'location_id': entry.location_id,
            'location_name': location.name if location else None,
            'product_template_id': entry.product_template_id,
            'product_template_name': template.name if template else None,
        },
    )


async def _capacity_for_update(
    db: AsyncSession, org_id: UUID, entry_id: UUID
) -> PutawayCapacity:
    """The limit an edit or a removal changes, read under its row lock.

    Both journal the limit as they read it: a request that reached it while
    another was changing it waits for that commit and reads what it really
    changes, so the same edit saved twice at once is journalled once.
    """
    entry = await db.scalar(
        select(PutawayCapacity)
        .where(
            PutawayCapacity.id == entry_id,
            PutawayCapacity.organization_id == org_id,
        )
        .with_for_update()
    )
    if entry is None:
        raise NotFoundException('putaway_capacity')
    return entry


async def _validate_location(db: AsyncSession, org_id: UUID, location_id: UUID) -> None:
    from .document_validation_service import validate_location_async

    try:
        await validate_location_async(db, org_id, location_id)
    except ValueError as exc:
        raise refusal_exception(exc) from exc


async def _validate_product(
    db: AsyncSession, org_id: UUID, product_template_id: UUID
) -> ProductTemplateDTO:
    template = await core_api.product_templates.get_async(
        db, org_id, product_template_id
    )
    if template is None:
        raise ServiceRejectionError('product_template_not_found')
    return template


async def _validate_precision(
    db: AsyncSession,
    template: ProductTemplateDTO,
    max_quantity: Any,
    org_id: UUID,
) -> None:
    """The limit speaks the product's stock unit, so it obeys that unit's
    rounding — the same rule every quantity for this product obeys.

    ``uom_id`` is read off the DTO by name: the field always exists, so a
    rename fails loudly here instead of quietly answering "this product has
    no unit" on the screen.
    """
    uom_id = template.uom_id
    if uom_id is None:
        return
    try:
        await core_api.uoms.validate_quantity_precision_async(
            db, uom_id, max_quantity, org_id
        )
    except ValueError as exc:
        raise refusal_exception(exc) from exc


async def _reorder_side(
    db: AsyncSession, org_id: UUID, location_id: UUID, template_id: UUID
) -> tuple[Any | None, bool]:
    """The replenishment side of the pair, read at response time: the rule
    wanting more than the shelf holds is a warning, not a refusal."""
    orders = await order_side_async(db, org_id)
    if orders is None:
        return None, False
    rules = await orders.list_reorder_rules_async(
        db, org_id, product_template_id=template_id, storage_location_id=location_id
    )
    if not rules:
        return None, False
    return rules[0].max_quantity, rules[0].max_quantity is not None


async def _out_with_names(
    db: AsyncSession,
    org_id: UUID,
    entry: PutawayCapacity,
) -> PutawayCapacityOut:
    dto = PutawayCapacityOut.model_validate(entry)
    location = await core_api.locations.get_async(db, org_id, entry.location_id)
    dto.location_name = location.name if location else None
    template = await core_api.product_templates.get_async(
        db, org_id, entry.product_template_id
    )
    dto.product_template_name = template.name if template else None
    uom_id = template.uom_id if template else None
    if uom_id is not None:
        uom = await core_api.uoms.get_async(db, uom_id, org_id)
        dto.product_unit_symbol = uom.symbol if uom else None
    rule_max, over = await _reorder_side(
        db, org_id, entry.location_id, entry.product_template_id
    )
    dto.reorder_max_quantity = rule_max
    dto.reorder_over_capacity = bool(
        over and rule_max is not None and rule_max > entry.max_quantity
    )
    return dto


@router.get('/putaway/capacity', response_model=PaginatedResponse[PutawayCapacityOut])
async def list_putaway_capacity(
    location_id: UUID | None = None,
    product_template_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    query = select(PutawayCapacity).where(PutawayCapacity.organization_id == org_id)
    if location_id is not None:
        query = query.where(PutawayCapacity.location_id == location_id)
    if product_template_id is not None:
        query = query.where(PutawayCapacity.product_template_id == product_template_id)
    query = query.order_by(PutawayCapacity.created_at.asc())
    entries = list((await db.execute(query)).scalars().all())
    page = [
        await _out_with_names(db, org_id, e) for e in entries[offset : offset + limit]
    ]
    return PaginatedResponse.from_slice(page, offset, limit, len(entries))


@router.post('/putaway/capacity', response_model=PutawayCapacityOut, status_code=201)
async def create_putaway_capacity(
    data: PutawayCapacityCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    await _validate_location(db, org_id, data.location_id)
    template = await _validate_product(db, org_id, data.product_template_id)
    await _validate_precision(db, template, data.max_quantity, org_id)

    duplicate = await db.scalar(
        select(PutawayCapacity)
        .where(
            PutawayCapacity.organization_id == org_id,
            PutawayCapacity.location_id == data.location_id,
            PutawayCapacity.product_template_id == data.product_template_id,
        )
        .with_for_update()
    )
    if duplicate is not None:
        raise ServiceRejectionError('putaway_capacity_exists')

    entry = PutawayCapacity(
        organization_id=org_id,
        location_id=data.location_id,
        product_template_id=data.product_template_id,
        max_quantity=data.max_quantity,
    )
    db.add(entry)
    # keep: the response resolves names for the pending row
    await db.flush()
    await db.refresh(entry)
    await _journal_capacity(db, current_user, entry, None, entry)
    return await _out_with_names(db, org_id, entry)


@router.put('/putaway/capacity/{entry_id}', response_model=PutawayCapacityOut)
async def update_putaway_capacity(
    entry_id: UUID,
    data: PutawayCapacityUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    entry = await _capacity_for_update(db, org_id, entry_id)
    template = await _validate_product(db, org_id, entry.product_template_id)
    await _validate_precision(db, template, data.max_quantity, org_id)
    before = record_settings(entry)
    entry.max_quantity = data.max_quantity
    await db.flush()
    await db.refresh(entry)
    await _journal_capacity(db, current_user, entry, before, entry)
    return await _out_with_names(db, org_id, entry)


@router.delete('/putaway/capacity/{entry_id}', status_code=204)
async def delete_putaway_capacity(
    entry_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    entry = await _capacity_for_update(db, org_id, entry_id)
    before = record_settings(entry)
    await _journal_capacity(db, current_user, entry, before, None)
    await db.delete(entry)


@router.get(
    '/putaway/capacity-settings',
    response_model=PaginatedResponse[PutawayLocationSettingOut],
)
async def list_putaway_location_settings(
    location_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Every shelf whose product mix was chosen, in one answer.

    A shelf nobody restricted has no row — mixed is the default — so this
    lists the restrictions that exist rather than a row per location, and a
    reader can tell a chosen "different products" from a shelf that was
    never touched. The settings screen reads all of them for the warehouse
    it shows instead of asking once per row.
    """
    org_id = require_org(current_user)
    query = select(PutawayLocationSetting).where(
        PutawayLocationSetting.organization_id == org_id
    )
    if location_id is not None:
        query = query.where(PutawayLocationSetting.location_id == location_id)
    query = query.order_by(PutawayLocationSetting.location_id)
    rows = list((await db.execute(query)).scalars().all())
    return PaginatedResponse.from_full_list(
        [PutawayLocationSettingOut.model_validate(row) for row in rows],
        offset=offset,
        limit=limit,
    )


@router.get(
    '/putaway/capacity-settings/{location_id}',
    response_model=PutawayLocationSettingOut,
)
async def get_putaway_location_setting(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    await _validate_location(db, org_id, location_id)
    setting = await db.scalar(
        select(PutawayLocationSetting).where(
            PutawayLocationSetting.organization_id == org_id,
            PutawayLocationSetting.location_id == location_id,
        )
    )
    if setting is None:
        # Absent row reads mixed: the default that keeps every
        # organization that never chose a restriction unchanged.
        return PutawayLocationSettingOut(location_id=location_id, single_product=False)
    return PutawayLocationSettingOut.model_validate(setting)


@router.put(
    '/putaway/capacity-settings/{location_id}',
    response_model=PutawayLocationSettingOut,
)
async def put_putaway_location_setting(
    location_id: UUID,
    data: PutawayLocationSettingUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    await _validate_location(db, org_id, location_id)
    setting = await db.scalar(
        select(PutawayLocationSetting)
        .where(
            PutawayLocationSetting.organization_id == org_id,
            PutawayLocationSetting.location_id == location_id,
        )
        .with_for_update()
    )
    # A shelf without a row reads mixed, so that is the side a first choice
    # is measured against: saving "mixed" over nothing moved nothing.
    before = (
        record_settings(setting) if setting is not None else {'single_product': False}
    )
    if setting is None:
        setting = PutawayLocationSetting(
            organization_id=org_id,
            location_id=location_id,
            single_product=data.single_product,
        )
        db.add(setting)
    else:
        setting.single_product = data.single_product
    await db.flush()
    await db.refresh(setting)
    location = await core_api.locations.get_async(db, org_id, location_id)
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='warehouse',
        subject='putaway-location',
        keys={'single_product'},
        before=before,
        after=setting,
        context={
            'location_id': location_id,
            'location_name': location.name if location else None,
        },
    )
    return PutawayLocationSettingOut.model_validate(setting)


async def _receiving_out(
    db: AsyncSession, org_id: UUID, row: WarehouseReceiving
) -> WarehouseReceivingOut:
    area = (
        await core_api.locations.get_async(db, org_id, row.receiving_location_id)
        if row.receiving_location_id is not None
        else None
    )
    return WarehouseReceivingOut(
        warehouse_id=row.warehouse_id,
        two_step=row.two_step,
        free_placement=row.free_placement,
        receiving_location_id=area.id if area else None,
        receiving_location_name=area.name if area else None,
    )


@router.get(
    '/putaway/receiving-modes', response_model=PaginatedResponse[WarehouseReceivingOut]
)
async def list_warehouse_receiving(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """The warehouses that chose how they receive; any other receives in one step."""
    org_id = require_org(current_user)
    rows = await list_receiving_modes_async(db, org_id)
    page = [
        await _receiving_out(db, org_id, row) for row in rows[offset : offset + limit]
    ]
    return PaginatedResponse.from_slice(page, offset, limit, len(rows))


@router.put(
    '/putaway/receiving-modes/{warehouse_id}', response_model=WarehouseReceivingOut
)
@map_service_errors
async def put_warehouse_receiving(
    warehouse_id: UUID,
    data: WarehouseReceivingUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Receive in one step, or into the receiving area with putaway later;
    keep fixed places per product, or store wherever there is room.

    Two steps make the warehouse's receiving area at once, inside it.
    """
    org_id = require_org(current_user)
    row = await set_receiving_mode_async(
        db,
        org_id,
        current_user.id,
        warehouse_id,
        two_step=data.two_step,
        free_placement=data.free_placement,
    )
    return await _receiving_out(db, org_id, row)


def _occupancy_cell(
    *,
    location_id: UUID,
    location_name: str | None,
    quantities: dict[UUID, Any],
    limits: dict[UUID, Any],
    template_names: dict[UUID, str],
    template_units: dict[UUID, str | None],
    items_count: int,
    unlisted: int = 0,
) -> dict[str, Any]:
    """One shelf's cell, read off the shared ``shelf_fill``.

    The fill is the sum of each limited product's share — the number the
    putaway planner decides by — so this cell can never call a shelf half
    empty that the planner treats as full. Each product keeps its own row
    with its share; one without a limit has none and marks the cell
    ``unmeasured``. ``capacity_used`` / ``capacity_max`` stay the pair of
    the product taking the largest share, named, for a reader who wants
    the quantities behind the percentage.

    ``unlisted`` counts the products standing there that ``quantities``
    leaves out (see ``shelf_fill``): they have no entry, and ``products``
    still counts them.
    """
    fill = shelf_fill(quantities, limits, unlisted=unlisted)
    rows: list[dict[str, Any]] = [
        {
            'product_template_id': share.product_template_id,
            'product_template_name': template_names.get(share.product_template_id),
            'product_unit_symbol': template_units.get(share.product_template_id),
            'quantity': share.quantity,
            'max_quantity': share.max_quantity,
            'share': (round(share.share * 100) if share.share is not None else None),
        }
        for share in fill.shares
    ]
    limited = [s for s in fill.shares if s.share is not None]
    largest = max(limited, key=lambda s: s.share or 0) if limited else None
    return {
        'location_id': location_id,
        'location_name': location_name,
        'entries': rows,
        'capacity_product_name': (
            template_names.get(largest.product_template_id) if largest else None
        ),
        'capacity_used': largest.quantity if largest else None,
        'capacity_max': largest.max_quantity if largest else None,
        'fill': fill.percent,
        'status': fill.status,
        'unmeasured': fill.unmeasured,
        'capped_products': len(limited),
        'products': sum(1 for q in quantities.values() if q and q > 0) + unlisted,
        'items_count': items_count,
    }


@router.get('/putaway/occupancy/{location_id}', response_model=PutawayOccupancyOut)
async def get_putaway_occupancy(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Occupancy of every shelf under one location, plus the two
    sentences the company overview quotes: which shelf is nearly full, and
    how many open receipt lines have nowhere to go.

    A shelf's fill is the sum of its products' shares (``shelf_fill``), the
    same sum the putaway planner decides by. A location with no limit at
    all carries no percentage — an unlimited shelf's fill is not zero, it is
    undefined, and inventing one from a count of records would be a lie
    with a colour on it.
    """
    from decimal import Decimal

    from sqlalchemy.orm import selectinload

    from . import document_types as dt
    from ._receipt_planning import ReceiptLocationPlanner, receipt_line_card_async
    from .models import Document, DocumentStatus, PutawayCapacity

    org_id = require_org(current_user)
    await _validate_location(db, org_id, location_id)
    descendant_ids = await core_api.locations.descendant_ids_async(
        db, org_id, location_id
    )
    scope = [location_id] + descendant_ids

    entries = list(
        (
            await db.execute(
                select(PutawayCapacity).where(
                    PutawayCapacity.organization_id == org_id,
                    in_ids(PutawayCapacity.location_id, scope),
                )
            )
        )
        .scalars()
        .all()
    )
    limits: dict[UUID, dict[UUID, Decimal]] = {}
    for entry in entries:
        limits.setdefault(entry.location_id, {})[entry.product_template_id] = (
            entry.max_quantity
        )
    # Every product standing in scope, limited or not: a product without a
    # limit is what makes a shelf's fill "unmeasured".
    quantities = await core_api.stock.quantities_by_shelf_async(
        db, org_id, storage_location_ids=list(scope)
    )
    template_ids = sorted(
        {e.product_template_id for e in entries}
        | {pid for shelf in quantities.values() for pid in shelf}
    )

    # Every location in the subtree gets a cell; only capped ones get a
    # percentage. A location with no entries has no limit — its fill is
    # undefined, not zero, and the view says contents without a percent.
    location_ids_of_entries = sorted(set(scope))
    names = await core_api.queries.get_storage_display_names_async(
        db, org_id, location_ids_of_entries
    )
    templates = await core_api.product_templates.names_and_units_async(
        db, org_id, template_ids
    )
    template_names = {
        tid: (templates[tid][0] if tid in templates else '') for tid in template_ids
    }
    template_units = {
        tid: (templates[tid][1] if tid in templates else None) for tid in template_ids
    }

    # Contents of every shelf in scope: what an uncapped cell shows instead
    # of a percentage (a count of records — never dressed up as a fill).
    item_counts = await core_api.locations.item_counts_by_location_async(
        db, org_id, scope
    )

    cells: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    for lid in location_ids_of_entries:
        cell = _occupancy_cell(
            location_id=lid,
            location_name=names.get(lid),
            quantities=quantities.get(lid, {}),
            limits=limits.get(lid, {}),
            template_names=template_names,
            template_units=template_units,
            items_count=item_counts.get(lid, 0),
        )
        cells.append(cell)
        fill = cell['fill']
        if fill is not None and cell['status'] in (
            STATUS_NEARLY_FULL,
            STATUS_OVER,
        ):
            signals.append(
                {
                    'code': 'location_over_capacity',
                    'location_name': names.get(lid),
                    'location_id': lid,
                    'fill': fill,
                }
            )

    # Open receipt lines whose every rule shelf is full: the planner answers
    # per line, the same way the preview does.
    stuck = 0
    open_docs = list(
        (
            await db.execute(
                select(Document)
                .options(selectinload(Document.lines))
                .where(
                    Document.organization_id == org_id,
                    Document.type.in_(sorted(dt._RECEIPT)),
                    Document.status.in_(
                        [DocumentStatus.DRAFT.value, DocumentStatus.CONFIRMED.value]
                    ),
                )
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    planner: ReceiptLocationPlanner | None = None
    for doc in open_docs:
        planner = await ReceiptLocationPlanner.for_document(db, doc, like=planner)
        for line in doc.lines:
            if line.executed_location_id is not None:
                continue
            named = line.item
            stock_template_id = await receipt_line_card_async(
                db,
                org_id,
                product_template_id=line.product_template_id,
                named=named,
                barcode=line.barcode,
            )
            decision = await planner.decide(
                named=named,
                stock_template_id=stock_template_id,
                line_target_id=line.target_location_id,
                quantity_stock=line.expected_quantity,
            )
            if decision.over_capacity:
                stuck += 1
    if stuck:
        signals.append({'code': 'receipt_lines_without_space', 'count': stuck})

    cells.sort(key=lambda c: c['location_name'] or '')
    return {'locations': cells, 'signals': signals}
