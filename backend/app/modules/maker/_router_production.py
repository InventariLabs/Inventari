"""Production order endpoints — create, list, preview, complete, cancel."""

from __future__ import annotations

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnprocessableException,
    map_service_errors,
)
from app.core.module_sdk import PaginatedResponse
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from . import (
    availability_service,
    output_batch,
    planning_service,
    production_reversal,
    production_service,
    recipe_service,
)
from ._router_bom import _attach_child_names
from ._schemas_production import (
    MonthlyResultItem,
    ProductionMadeCreate,
    ProductionOrderCancel,
    ProductionOrderComplete,
    ProductionOrderCreate,
    ProductionOrderFinish,
    ProductionOrderLineRead,
    ProductionOrderListResponse,
    ProductionOrderRead,
    ProductionOrderStart,
    ProductionOrderUpdate,
    ProductionPortionCreate,
    ProductionPortionRead,
    ProductionPreviewResponse,
    ProductionStepRead,
    ProductionStepTick,
    ProductionStockMoveRead,
    ShortageItemRead,
    ShortageShoppingListResponse,
)
from .exceptions import (
    EmptyBillOfMaterialsError,
    InsufficientStockError,
    ShortageBlockedError,
    ShortageError,
    ShortageWarningError,
)
from .models import ProductionOrder, ProductionOrderLine, ProductionPortion

router = APIRouter(prefix='/production', tags=['maker'])


def _shortage_refusal(
    error: str,
    exc: ShortageError,
    *,
    message_key: str = 'production_short_of_stock',
    **context: object,
) -> UnprocessableException:
    """The 422 the shortage dialogs read: ``error`` picks the dialog, ``shortages`` fills it."""
    return UnprocessableException(
        error,
        get_error_message(message_key, get_current_lang()),
        details={'error': error, 'shortages': exc.to_detail(), **context},
    )


def _empty_bom_refusal(exc: EmptyBillOfMaterialsError) -> UnprocessableException:
    """The 422 for a recipe with no ingredients; it names the recipe to go and fix."""
    return UnprocessableException(
        'empty_bom',
        get_error_message('production_no_recipe', get_current_lang()),
        details=exc.to_detail(),
    )


async def _output_uom_symbols(
    db: AsyncSession, org_id: UUID, orders: list[ProductionOrder]
) -> dict[UUID, str | None]:
    """Map output template -> unit symbol for the given orders.

    Batched on purpose: planned and actual quantities are meaningless without
    a measure, and resolving one per row would be an N+1 on the list page.
    """
    template_ids = {o.output_template_id for o in orders if o.output_template_id}
    if not template_ids:
        return {}
    templates = await core_api.product_templates.get_many_async(
        db, org_id, list(template_ids)
    )
    uom_symbols = {
        uom.id: uom.symbol for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    return {
        tid: uom_symbols.get(tpl.uom_id) if tpl.uom_id else None
        for tid, tpl in templates.items()
    }


async def _read_with_uom(
    db: AsyncSession,
    org_id: UUID,
    order: ProductionOrder,
    lines: list[ProductionOrderLine] | None = None,
    produced_item_name: str | None = None,
) -> ProductionOrderRead:
    """The one constructor of a single order's answer, whichever door it came through.

    A draft carries the shortage completion would refuse on — the count and
    the refusal's own list — here, not at the call sites, so create, update,
    duplicate and the read can never tell a client different things about
    the same order. An order past the draft has no signal (null), and the
    lookup returns before touching the database for it.
    """
    symbols = await _output_uom_symbols(db, org_id, [order])
    shortage_signals = await availability_service.shortage_signals_for_orders(
        db, org_id, [order]
    )
    items = shortage_signals.get(order.id)
    plan_coverage = await _plan_coverage_of(db, org_id, [order])
    portions = (
        await production_service.list_portions(db, org_id, order.id)
        if order.status in ('IN_PROGRESS', 'COMPLETED', 'REVERSED')
        else []
    )
    read = _to_read(
        order,
        lines=lines,
        portions=portions,
        produced_item_name=produced_item_name,
        output_uom_symbol=symbols.get(order.output_template_id),
        plan_coverage=plan_coverage.get(order.id),
        shortage_count=len(items) if items is not None else None,
        shortage_items=(
            [ShortageItemRead.model_validate(item) for item in items]
            if items is not None
            else None
        ),
    )
    # The batch as it stands now — a hold placed since the run closed shows
    # here — and the shelf life a closing run counts its best-before from.
    batch: dict[str, object] = {
        'shelf_life_days': await output_batch.get_shelf_life_async(
            db, org_id, order.output_template_id
        )
    }
    if order.output_lot_id is not None:
        lots = await output_batch.lots_of_run_async(db, org_id, order)
        batch['output_batches'] = output_batch.run_batch_reads(lots)
        if lots:
            # The run's own batch, first of them: what a screen that speaks of
            # one batch reads.
            batch['output_lot_status'] = lots[0].status
            batch['best_before'] = lots[0].expiry_date or lots[0].use_by_date
    return read.model_copy(update=batch)


async def _plan_coverage_of(
    db: AsyncSession, org_id: UUID, orders: list[ProductionOrder]
) -> dict[UUID, planning_service.PlanCoverage]:
    """The plan's coverage of the drafts among *orders* (nothing for the rest).

    The queue a draft is measured in is every draft of the organization, not
    the page, so a run on page two still counts the runs before it; the
    lookup returns before touching the database when no draft is asked for.
    """
    if not any(o.status == 'DRAFT' for o in orders):
        return {}
    return await planning_service.coverage_for_drafts(db, org_id)


def _to_read(
    order: ProductionOrder,
    lines: list[ProductionOrderLine] | None = None,
    produced_item_name: str | None = None,
    output_uom_symbol: str | None = None,
    shortage_count: int | None = None,
    shortage_items: list[ShortageItemRead] | None = None,
    portions: list[ProductionPortion] | None = None,
    plan_coverage: planning_service.PlanCoverage | None = None,
    uncosted_ingredients: int = 0,
) -> ProductionOrderRead:
    line_rows = lines if lines is not None else []
    return ProductionOrderRead(
        id=order.id,
        organization_id=order.organization_id,
        output_template_id=order.output_template_id,
        recipe_id=order.recipe_id,
        number=order.number,
        planned_qty=order.planned_qty,
        actual_qty=order.actual_qty,
        overproduced=order.overproduced,
        scrap_qty=order.scrap_qty,
        output_location_id=order.output_storage_location_id,
        status=order.status,
        total_cost=order.total_cost,
        estimated_total_cost=order.estimated_total_cost,
        production_date=order.production_date,
        notes=order.notes,
        output_lot_name=order.output_lot_name,
        output_lot_id=order.output_lot_id,
        created_by=order.created_by,
        completed_by=order.completed_by,
        created_at=order.created_at,
        completed_at=order.completed_at,
        output_template_name=(
            order.output_template.name if order.output_template is not None else None
        ),
        output_uom_symbol=output_uom_symbol,
        cancel_reason=order.cancel_reason,
        produced_item_id=order.produced_item_id,
        produced_item_name=produced_item_name,
        unit_cost=(
            order.total_cost / order.actual_qty
            if order.total_cost is not None and order.actual_qty
            else None
        ),
        shortage_count=shortage_count,
        shortage_items=shortage_items,
        coverage=plan_coverage.status if plan_coverage is not None else None,
        coverage_items=(
            [ShortageItemRead.model_validate(item) for item in plan_coverage.items]
            if plan_coverage is not None
            else None
        ),
        unit_cost_snapshot=order.unit_cost_snapshot,
        reference_price_snapshot=order.reference_price_snapshot,
        result_per_unit=order.result_per_unit,
        result_per_batch=order.result_per_batch,
        lines=[ProductionOrderLineRead.model_validate(line) for line in line_rows],
        uncosted_ingredients=uncosted_ingredients,
        started_on=order.started_on,
        planned_for=order.planned_for,
        material_cost=order.material_cost,
        unshelved_cost=order.unshelved_cost,
        steps=[ProductionStepRead.model_validate(step) for step in order.steps or []],
        portions=[
            ProductionPortionRead.model_validate(portion) for portion in portions or []
        ],
    )


async def _attach_source_location_names(
    db: AsyncSession, org_id: UUID, lines: list[ProductionOrderLine]
) -> None:
    """Set a transient ``source_storage_location_name`` on each line.

    Same trick as ``_attach_child_names``: an unmapped attribute the schema
    picks up on validation, so the ORM model stays untouched.
    """
    ids = {
        line.source_storage_location_id
        for line in lines
        if line.source_storage_location_id is not None
    }
    names: dict[UUID, str] = {}
    for storage_id in ids:
        storage = await core_api.locations.get_async(db, org_id, storage_id)
        if storage is not None:
            names[storage_id] = storage.name
    for line in lines:
        setattr(  # noqa: B010
            line,
            'source_location_name',
            names.get(line.source_storage_location_id)
            if line.source_storage_location_id
            else None,
        )


@router.get(
    '/orders',
    response_model=ProductionOrderListResponse,
)
async def list_production_orders(
    output_template_id: UUID | None = Query(None),
    status: str | None = Query(None, pattern='^(DRAFT|COMPLETED|CANCELLED|REVERSED)$'),
    sort: str = Query('newest', pattern='^(newest|oldest|cost_desc)$'),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    planned_from: date_type | None = Query(None),
    planned_to: date_type | None = Query(None),
    # ``skip`` stays the wire name: the maker screens send it and the REST
    # query shipped with 0.11. Everything below the router says ``offset``.
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderListResponse:
    orders, total = await production_service.list_orders(
        db,
        org_id,
        output_template_id=output_template_id,
        status=status,
        sort=sort,
        date_from=date_from,
        date_to=date_to,
        planned_from=planned_from,
        planned_to=planned_to,
        offset=skip,
        limit=limit,
    )
    order_uom_symbols = await _output_uom_symbols(db, org_id, list(orders))
    # The detail page calls a draft's shortage a blocker; a card that said
    # nothing about it made the planner open drafts one by one to learn
    # which runs would be refused. One service call for the page, listing
    # the way completion refuses — see shortage_signals_for_orders.
    shortage_signals = await availability_service.shortage_signals_for_orders(
        db, org_id, list(orders)
    )
    plan_coverage = await _plan_coverage_of(db, org_id, list(orders))
    # A closed run's total leaves out an ingredient drawn with no cost; the
    # card says so beside the figure, as the run's page does.
    uncosted = await recipe_service.uncosted_line_counts(
        db, [o.id for o in orders if o.status != 'DRAFT']
    )
    return ProductionOrderListResponse.from_slice(
        items=[
            _to_read(
                o,
                uncosted_ingredients=uncosted.get(o.id, 0),
                output_uom_symbol=order_uom_symbols.get(o.output_template_id),
                plan_coverage=plan_coverage.get(o.id),
                shortage_count=(
                    len(items)
                    if (items := shortage_signals.get(o.id)) is not None
                    else None
                ),
            )
            for o in orders
        ],
        offset=skip,
        limit=limit,
        total=total,
    )


@router.get(
    '/monthly-result',
    # list-envelope-exception: one entry per calendar month asked for, a fixed series
    response_model=list[MonthlyResultItem],
)
async def get_monthly_result(
    months: int = Query(6, ge=1, le=24),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[MonthlyResultItem]:
    """Monthly financial result from order snapshots.

    Aggregates ``result_per_unit × actual_qty`` over COMPLETED orders with a
    result snapshot, one entry per calendar month (zero months included,
    oldest → newest).
    """
    rows = await production_service.monthly_result(db, org_id, months=months)
    return [MonthlyResultItem(**row) for row in rows]


@router.post(
    '/orders',
    response_model=ProductionOrderRead,
    status_code=201,
)
async def create_production_order(
    data: ProductionOrderCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Create a DRAFT production order.

    respects ``create_on_shortage_strategy`` —
    - ALLOW: always creates.
    - WARN (the default): returns 422 with shortage list unless
      ``confirm_shortage=true``.
    - BLOCK: returns 422 with shortage list, DRAFT never created —
      ``confirm_shortage`` does not lift it.
    """
    try:
        order = await production_service.create_order(db, org_id, data, current_user)
    except ShortageBlockedError as exc:
        raise _shortage_refusal('shortage_blocked', exc) from exc
    except ShortageWarningError as exc:
        raise _shortage_refusal('shortage_warning', exc) from exc
    await db.refresh(order)
    return await _read_with_uom(db, org_id, order)


@router.post(
    '/orders/made',
    response_model=ProductionOrderRead,
    status_code=201,
)
@map_service_errors
async def record_made_production(
    data: ProductionMadeCreate,
    # The run opens a core Item for its output, like completing one does.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Record a run that already happened: created and completed in one step.

    ``planned_qty`` is what came out, in the product's unit. An ingredient
    the records hold too little of does not refuse the run: what they hold
    is consumed, the rest is the line's ``shortfall_qty``, and the
    ingredient is put up for a count in To do. Returns 422
    ``insufficient_stock`` only for a line whose measure cannot be compared
    with its stock, and ``empty_bom`` for a recipe with no ingredients.
    """
    try:
        order = await production_service.record_made(db, org_id, data, current_user)
    except InsufficientStockError as exc:
        # The shape completion's refusal carries, so the same dialog reads it.
        raise _shortage_refusal(
            'insufficient_stock',
            exc,
            message_key='production_ingredient_unmeasurable',
            short_at_create=exc.short_at_create,
        ) from exc
    except EmptyBillOfMaterialsError as exc:
        raise _empty_bom_refusal(exc) from exc
    await db.refresh(order)
    lines = await production_service.list_lines(db, org_id, order.id)
    await _attach_child_names(db, org_id, lines)
    await _attach_source_location_names(db, org_id, lines)
    return await _read_with_uom(db, org_id, order, lines=lines)


@router.post(
    '/orders/preview',
    response_model=ProductionPreviewResponse,
)
@map_service_errors
async def preview_production(
    data: ProductionOrderCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionPreviewResponse:
    """Dry-run: cost breakdown, shortages and cost per unit, touching no stock.

    No consume, no output item, no stock movement — what the person sees
    before saving a run as made or as planned.
    """
    preview = await production_service.preview_production(db, org_id, data)
    preview.shelf_life_days = await output_batch.get_shelf_life_async(
        db, org_id, data.output_template_id
    )
    return preview


@router.post(
    '/orders/shortages/shopping-list',
    response_model=ShortageShoppingListResponse,
    dependencies=[require_permission('shopping_lists:write')],
)
@map_service_errors
async def add_shortages_to_shopping_list(
    data: ProductionOrderCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ShortageShoppingListResponse:
    """Put what a planned run lacks on the active shopping list.

    403 when the shopping lists module is off for the organization.
    """
    return await production_service.add_shortages_to_shopping_list(
        db, org_id, data, current_user, get_current_lang()
    )


@router.post(
    '/orders/{order_id}/complete',
    response_model=ProductionOrderRead,
)
@map_service_errors
async def complete_production_order(
    order_id: UUID,
    data: ProductionOrderComplete = ProductionOrderComplete(),
    # Completing a run opens a core Item for the output — items work, the
    # same door the equipment import asks beside its own permission.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Complete a DRAFT order: consume inputs, produce output, record costs.

    Optional body ``{actual_qty}``: real output quantity.
    Defaults to ``planned_qty`` when omitted.

    returns 422 with an actionable shortage list when ingredients
    are insufficient (instead of a bare 500).

    Returns 422 ``empty_bom`` when the recipe lists no ingredients — such a run
    would produce the output against zero consumption.
    """
    try:
        order = await production_service.complete_production(
            db,
            org_id,
            order_id,
            current_user,
            actual_qty=data.actual_qty,
            best_before=data.best_before,
            ingredient_lots=data.ingredient_lots,
            made_on=data.made_on,
        )
    except InsufficientStockError as exc:
        raise _shortage_refusal(
            'insufficient_stock',
            exc,
            # Was the run born over stock? The dialog distinguishes
            # "never enough" from "ran out since the draft was created"
            # instead of guessing which theft happened.
            short_at_create=exc.short_at_create,
        ) from exc
    except EmptyBillOfMaterialsError as exc:
        raise _empty_bom_refusal(exc) from exc
    await db.refresh(order)
    return await _read_with_uom(db, org_id, order)


async def _read_after(
    db: AsyncSession, org_id: UUID, order: ProductionOrder
) -> ProductionOrderRead:
    """The run as the page reads it after a step moved it — lines and names too."""
    await db.refresh(order)
    lines = await production_service.list_lines(db, org_id, order.id)
    await _attach_child_names(db, org_id, lines)
    await _attach_source_location_names(db, org_id, lines)
    return await _read_with_uom(db, org_id, order, lines=lines)


@router.post(
    '/orders/{order_id}/start',
    response_model=ProductionOrderRead,
)
@map_service_errors
async def start_production_order(
    order_id: UUID,
    data: ProductionOrderStart = ProductionOrderStart(),
    # Starting takes the ingredients off their records, as completing does.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Start a DRAFT order: take its ingredients now, finish it later.

    The run reads ``IN_PROGRESS`` until it is finished, in portions or at
    once. Refuses like completion does — 422 with the shortage list when
    the ingredients are not there, ``empty_bom`` for a recipe with no lines.
    """
    try:
        order = await production_service.start_production(
            db,
            org_id,
            order_id,
            current_user,
            started_on=data.started_on,
            ingredient_lots=data.ingredient_lots,
        )
    except InsufficientStockError as exc:
        raise _shortage_refusal(
            'insufficient_stock', exc, short_at_create=exc.short_at_create
        ) from exc
    except EmptyBillOfMaterialsError as exc:
        raise _empty_bom_refusal(exc) from exc
    return await _read_after(db, org_id, order)


@router.post(
    '/orders/{order_id}/portions',
    response_model=ProductionOrderRead,
    status_code=201,
)
@map_service_errors
async def record_production_portion(
    order_id: UUID,
    data: ProductionPortionCreate,
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Put a portion of an in-progress run's output on the shelf, on its day."""
    await production_service.record_portion(
        db,
        org_id,
        order_id,
        current_user,
        qty=data.qty,
        made_on=data.made_on,
        lot_name=data.output_lot_name,
        best_before=data.best_before,
    )
    order = await production_service.get_order(db, org_id, order_id)
    if order is None:
        raise NotFoundException('production_order', get_current_lang())
    return await _read_after(db, org_id, order)


@router.post(
    '/orders/{order_id}/finish',
    response_model=ProductionOrderRead,
)
@map_service_errors
async def finish_production_order(
    order_id: UUID,
    data: ProductionOrderFinish = ProductionOrderFinish(),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Finish an in-progress order: the rest of its output, its final cost.

    ``actual_qty`` is what the whole run made, portions included.
    """
    order = await production_service.finish_production(
        db,
        org_id,
        order_id,
        current_user,
        actual_qty=data.actual_qty,
        finished_on=data.finished_on,
        lot_name=data.output_lot_name,
        best_before=data.best_before,
    )
    return await _read_after(db, org_id, order)


@router.put(
    '/orders/{order_id}/steps/{index}',
    response_model=ProductionOrderRead,
)
@map_service_errors
async def tick_production_step(
    order_id: UUID,
    index: int,
    data: ProductionStepTick,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Mark a process step of an in-progress run done on a day (null clears it)."""
    order = await production_service.tick_step(
        db, org_id, order_id, index, data.done_on, current_user
    )
    return await _read_after(db, org_id, order)


@router.post(
    '/orders/{order_id}/cancel',
    response_model=ProductionOrderRead,
    # The person running the batch executes it; taking a run back is the
    # manager's call, the same split the warehouse module draws between
    # executing a document and cancelling it.
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def cancel_production_order(
    order_id: UUID,
    data: ProductionOrderCancel = ProductionOrderCancel(),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    # A run in progress gives its ingredients back to their records, as
    # starting it took them: items work, beside the manager's call.
    existing = await production_service.get_order(db, org_id, order_id)
    if (
        existing is not None
        and existing.status == 'IN_PROGRESS'
        and not current_user.has_permission(SystemPermission.ITEMS_WRITE)
    ):
        raise ForbiddenException(
            get_error_message('insufficient_permissions', get_current_lang())
        )
    order = await production_service.cancel_order(
        db, org_id, order_id, current_user, reason=data.reason
    )
    await db.refresh(order)
    return await _read_with_uom(db, org_id, order)


@router.post(
    '/orders/{order_id}/reverse',
    response_model=ProductionOrderRead,
    # Taking a completed run back moves stock the run already posted: the
    # manager's call, as cancelling a draft is.
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def reverse_production_order(
    order_id: UUID,
    # The reversal writes core Items — the output's record and, for an
    # ingredient whose record is gone, a new one — so items work too.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Take a completed run back: ingredients return, the output leaves.

    The run stays as it was, marked REVERSED; the movements of the way back
    name it, beside the ones of the way in. Refused (400) for a run that is
    not completed and for one whose output has since left its shelf.
    """
    order = await production_reversal.reverse_production(
        db, org_id, order_id, current_user
    )
    await db.refresh(order)
    return await _read_with_uom(db, org_id, order)


@router.get(
    '/orders/{order_id}',
    response_model=ProductionOrderRead,
)
async def get_production_order(
    order_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    order = await production_service.get_order(db, org_id, order_id)
    if order is None:
        raise NotFoundException('production_order', get_current_lang())
    lines = await production_service.list_lines(db, org_id, order_id)
    # Resolve display names (FE renders names, not raw UUIDs).
    await _attach_child_names(db, org_id, lines)
    await _attach_source_location_names(db, org_id, lines)
    produced_item_name: str | None = None
    if order.produced_item_id is not None:
        produced = await core_api.items.get_async(db, org_id, order.produced_item_id)
        produced_item_name = produced.name if produced is not None else None
    return await _read_with_uom(
        db, org_id, order, lines=lines, produced_item_name=produced_item_name
    )


@router.patch(
    '/orders/{order_id}',
    response_model=ProductionOrderRead,
)
@map_service_errors
async def update_production_order(
    order_id: UUID,
    data: ProductionOrderUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Patch editable fields of a DRAFT order (qty, date, notes)."""
    order = await production_service.update_order(
        db, org_id, order_id, data, current_user
    )
    await db.refresh(order)
    return await _read_with_uom(db, org_id, order)


@router.post(
    '/orders/{order_id}/duplicate',
    response_model=ProductionOrderRead,
    status_code=201,
)
@map_service_errors
async def duplicate_production_order(
    order_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionOrderRead:
    """Create a fresh DRAFT order seeded from an existing one.

    A copy is a new plan: under BLOCK the stock has to cover it, and the
    refusal is the creation's own 422 with the shortage list.
    """
    try:
        order = await production_service.duplicate_order(
            db, org_id, order_id, current_user
        )
    except ShortageBlockedError as exc:
        raise _shortage_refusal('shortage_blocked', exc) from exc
    await db.refresh(order)
    return await _read_with_uom(db, org_id, order)


@router.get(
    '/orders/{order_id}/stock-moves',
    response_model=PaginatedResponse[ProductionStockMoveRead],
)
async def get_production_stock_moves(
    order_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[ProductionStockMoveRead]:
    """Return the stock moves attributed to this production order.

    Includes both ingredient consumption moves (from_location → None) and
    the output receipt move (None → output_location), with the lot for
    traceability. Products, lots and locations come back named, since a truncated
    UUID identifies nothing to the person reading the table.
    """
    total = await core_api.stock_moves.count_by_reference_async(
        db, org_id, 'maker_production', order_id
    )
    moves = await core_api.stock_moves.list_by_reference_async(
        db, org_id, 'maker_production', order_id, limit=limit, offset=offset
    )
    if not moves:
        return PaginatedResponse.from_slice([], offset, limit, total)

    templates = await core_api.product_templates.list_for_org_async(
        db, org_id, limit=10_000
    )
    template_map = {t.id: t for t in templates}
    template_names = {t.id: t.name for t in templates}
    uom_symbols = {
        uom.id: uom.symbol for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }

    lot_names: dict[UUID, str] = {}
    lot_template_ids = {m.product_template_id for m in moves if m.lot_id is not None}
    for template_id in lot_template_ids:
        for lot in await core_api.stock.list_lots_async(db, org_id, template_id):
            lot_names[lot.id] = lot.name

    location_names: dict[UUID, str] = {}
    for location_id in {
        *(m.from_location_id for m in moves if m.from_location_id is not None),
        *(m.to_location_id for m in moves if m.to_location_id is not None),
    }:
        location = await core_api.locations.get_async(db, org_id, location_id)
        if location is not None:
            location_names[location_id] = location.name

    rows = [
        ProductionStockMoveRead(
            id=move.id,
            product_template_id=move.product_template_id,
            product_template_name=template_names.get(move.product_template_id),
            from_location_id=move.from_location_id,
            to_location_id=move.to_location_id,
            from_location_name=(
                location_names.get(move.from_location_id)
                if move.from_location_id
                else None
            ),
            to_location_name=(
                location_names.get(move.to_location_id) if move.to_location_id else None
            ),
            quantity=move.quantity,
            uom_symbol=(
                uom_symbols.get(template.uom_id)
                if (template := template_map.get(move.product_template_id))
                and template.uom_id
                else None
            ),
            lot_id=move.lot_id,
            lot_code=lot_names.get(move.lot_id) if move.lot_id else None,
            created_at=move.created_at,
        )
        for move in moves
    ]
    return PaginatedResponse.from_slice(rows, offset, limit, total)
