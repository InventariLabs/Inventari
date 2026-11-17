"""Planning across runs: the combined needs of planned runs and ordering what is missing."""

from __future__ import annotations

from datetime import date as date_type
from decimal import ROUND_UP, Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import map_service_errors
from app.core.modules import require_module
from app.i18n.service import get_current_lang

from . import planning_needs, production_service
from ._schemas_planning import (
    NeedRowRead,
    NeedsRead,
    NeedsScope,
    OrderedLineRead,
    OrderedPurchaseRead,
    OrderMissingRead,
    PlanIntermediatesRead,
    PlannedIntermediateRead,
)
from ._schemas_production import ProductionOrderCreate

router = APIRouter(prefix='/production/needs', tags=['maker'])


def _row(row: planning_needs.NeedRow) -> NeedRowRead:
    return NeedRowRead.model_validate(row)


@router.get('', response_model=NeedsRead)
@map_service_errors
async def get_combined_needs(
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    order_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> NeedsRead:
    """What the planned runs of a period (or one run) need, in one list.

    Per ingredient: what is needed, what is in stock once the runs planned
    before the period have taken theirs, what open purchase orders still
    expect (with their dates) and what is still missing. ``on_order`` is null
    while purchasing is off.
    """
    view = await planning_needs.needs_for(
        db, org_id, date_from=date_from, date_to=date_to, order_id=order_id
    )
    return NeedsRead(
        rows=[_row(r) for r in view.rows],
        purchasing=view.purchasing,
        run_count=view.run_count,
        unmeasured=view.unmeasured,
    )


@router.post(
    '/order',
    response_model=OrderMissingRead,
    dependencies=[
        Depends(require_module('purchase_orders')),
        require_permission('purchase_orders:write'),
    ],
)
@map_service_errors
async def order_missing(
    scope: NeedsScope,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> OrderMissingRead:
    """Order what is missing: a draft purchase order per supplier.

    Each ingredient goes to the supplier with the lowest price, in that
    supplier's unit. Ingredients nobody offers go to the shopping list;
    ingredients with a recipe of their own come back as ``to_make`` — they are
    planned as runs, not bought.
    """
    done = await planning_needs.order_missing(
        db,
        org_id,
        current_user,
        get_current_lang(),
        date_from=scope.date_from,
        date_to=scope.date_to,
        order_id=scope.order_id,
    )
    return OrderMissingRead(
        purchase_orders=[
            OrderedPurchaseRead(
                purchase_order_id=po.purchase_order_id,
                number=po.number,
                partner_id=po.partner_id,
                lines=[
                    OrderedLineRead.model_validate(line, from_attributes=True)
                    for line in po.lines
                ],
            )
            for po in done.purchase_orders
        ],
        shopping_list_added=done.shopping_list_added,
        shopping_list_name=done.shopping_list_name,
        unplaced=[_row(r) for r in done.unplaced],
        to_make=[_row(r) for r in done.to_make],
    )


@router.post(
    '/plan-intermediates',
    response_model=PlanIntermediatesRead,
    status_code=201,
)
@map_service_errors
async def plan_intermediates(
    scope: NeedsScope,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PlanIntermediatesRead:
    """Plan a run of each missing intermediate product, on the day it is first needed."""
    view = await planning_needs.needs_for(
        db,
        org_id,
        date_from=scope.date_from,
        date_to=scope.date_to,
        order_id=scope.order_id,
    )
    runs: list[PlannedIntermediateRead] = []
    for row in view.rows:
        if row.action != 'make' or row.missing <= 0 or row.output_location_id is None:
            continue
        order = await production_service.create_order(
            db,
            org_id,
            ProductionOrderCreate(
                output_template_id=row.template_id,
                planned_qty=row.missing.quantize(Decimal('0.001'), rounding=ROUND_UP),
                output_location_id=row.output_location_id,
                production_date=row.needed_by,
                confirm_shortage=True,
            ),
            current_user,
            ask_the_strategy=False,
        )
        runs.append(
            PlannedIntermediateRead(
                order_id=order.id,
                number=order.number,
                template_id=row.template_id,
                name=row.name,
                planned_qty=order.planned_qty,
                production_date=order.production_date,
            )
        )
    return PlanIntermediatesRead(runs=runs)
