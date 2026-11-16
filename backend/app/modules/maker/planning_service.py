"""Planned runs measured against one shelf, one after another.

A draft's own availability check reads the shelf as if it were the only run
there. Two drafts that each need six of ten flour then both read as covered,
while together they need twelve. Planning reads the drafts as a queue: by
planned day, then by creation, each run counts only what the runs before it
left. A run with no planned day waits behind every dated one.

This is a planning view, not completion's verdict. Completion judges the shelf
as it is when the run is closed (``availability_service``), and a draft that is
behind another in the queue is still completable while the shelf holds enough
for it alone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ProductTemplateDTO, UomDTO
from app.core.public_api import core_api

from . import bom_service, recipe_service
from .availability_service import (
    ShortageItem,
    _aggregate_needs,
    _get_available_stock_batch,
    _resolve_scope,
    _shortages_from_needs,
)
from .models import MakerRecipe, ProductionOrder
from .stock_first import StockPool

CoverageStatus = Literal['covered', 'partial', 'short']


@dataclass(frozen=True)
class PlanCoverage:
    """How far the shelf, after the runs queued before this one, covers it.

    ``items`` are the ingredients that fall short, stated against what was
    left for this run — the same row shape the shortage list carries.
    """

    status: CoverageStatus
    items: list[ShortageItem] = field(default_factory=list)


class _Shelf:
    """What is left of the stock of one availability scope as runs claim it."""

    def __init__(self, pool: StockPool) -> None:
        self.pool = pool
        self.left: dict[UUID, Decimal] = {}


def _status(
    needs: dict[UUID, Decimal], shortages: list[ShortageItem]
) -> CoverageStatus:
    """Covered, partly covered, or short, from the ingredients that fall short.

    Partly covered means some of what the run needs is there — an ingredient
    that is fully met, or short but not at nothing. Short means none of it is.
    """
    if not shortages:
        return 'covered'
    if len(shortages) < len(needs):
        return 'partial'
    if any(item.convertible and item.available > 0 for item in shortages):
        return 'partial'
    return 'short'


async def queued_drafts(
    db: AsyncSession, organization_id: UUID
) -> list[ProductionOrder]:
    """Every draft run with a recipe, in the order they claim the shelf.

    By planned day, then by creation; a run with no planned day waits behind
    every dated one. The one ordering both the coverage and the combined needs
    read, so they cannot disagree about who goes first.
    """
    return list(
        (
            await db.scalars(
                select(ProductionOrder)
                .where(
                    ProductionOrder.organization_id == organization_id,
                    ProductionOrder.status == 'DRAFT',
                    ProductionOrder.recipe_id.is_not(None),
                )
                .order_by(
                    ProductionOrder.production_date.asc().nulls_last(),
                    ProductionOrder.created_at,
                    ProductionOrder.number,
                    ProductionOrder.id,
                )
            )
        ).all()
    )


def planned_day(order: ProductionOrder) -> tuple[bool, date]:
    """Where a run stands on the calendar; a run with no planned day is last.

    What a run makes is there for the runs planned on its day or after it —
    the same day included, whatever order they were created in.
    """
    day = order.production_date
    return (day is None, day or date.min)


def _expected_output(
    queue: list[ProductionOrder],
    scope_of: Callable[[ProductionOrder], UUID | None],
) -> dict[tuple[bool, date], dict[UUID | None, dict[UUID, Decimal]]]:
    """What the draft runs will make, per planned day and scope.

    A sub-assembly that a draft run already makes is not made again by the run
    that needs it, so the pool and the shelf both count it, in the scope of
    the run that makes it — from the run's planned day on, for the runs that
    come on that day or after it, not for the ones before.
    """
    expected: dict[tuple[bool, date], dict[UUID | None, dict[UUID, Decimal]]] = {}
    for order in queue:
        per_scope = expected.setdefault(planned_day(order), {}).setdefault(
            scope_of(order), {}
        )
        per_scope[order.output_template_id] = (
            per_scope.get(order.output_template_id, Decimal('0')) + order.planned_qty
        )
    return expected


def _add_expected(
    left: dict[UUID, Decimal], expected: dict[UUID, Decimal], children: set[UUID]
) -> None:
    """Put what planned runs will make on the shelf the coverage reads."""
    for template_id, qty in expected.items():
        if template_id in children:
            left[template_id] = left.get(template_id, Decimal('0')) + qty


async def _explode_by_day(
    db: AsyncSession,
    organization_id: UUID,
    queue: list[ProductionOrder],
    expected: dict[tuple[bool, date], dict[UUID | None, dict[UUID, Decimal]]],
    shelves: dict[UUID | None, _Shelf],
    scope_of: Callable[[ProductionOrder], UUID | None],
) -> list[list[tuple[UUID, Decimal, str, UUID | None]] | None]:
    """Explode the queue one planned day at a time, in queue order.

    What the runs of a day make is put on the pool just before that day's
    runs explode, so it serves them and the days after, never the runs
    planned before it.
    """
    flats: list[list[tuple[UUID, Decimal, str, UUID | None]] | None] = []
    for day, per_scope in expected.items():
        for scope, per_template in per_scope.items():
            for template_id, qty in per_template.items():
                shelves[scope].pool.expect(template_id, qty)
        flats += await bom_service.explode_in_sequence(
            db,
            organization_id,
            [
                (o.recipe_id, o.planned_qty, shelves[scope_of(o)].pool)
                for o in queue
                if planned_day(o) == day and o.recipe_id is not None
            ],
        )
    return flats


async def coverage_for_drafts(
    db: AsyncSession, organization_id: UUID
) -> dict[UUID, PlanCoverage]:
    """The coverage of every draft run that has a recipe to measure.

    One queue for the organization: each availability scope (the whole
    organization, or a run's own output shelf under PER_LOCATION) has its
    own stock, spent by the drafts that are measured in it. Drafts without a
    recipe, with an empty formula or with a yield that cannot scale a plan
    have nothing to forecast and get no entry.
    """
    drafts = await queued_drafts(db, organization_id)
    if not drafts:
        return {}

    yields = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(MakerRecipe.id, MakerRecipe.batch_yield_qty).where(
                    MakerRecipe.id.in_({o.recipe_id for o in drafts}),
                    MakerRecipe.organization_id == organization_id,
                )
            )
        ).all()
    }
    queue = [o for o in drafts if (yields.get(o.recipe_id) or Decimal('0')) > 0]
    if not queue:
        return {}

    settings = await recipe_service.get_settings(db, organization_id, for_update=False)

    def _scope(order: ProductionOrder) -> UUID | None:
        return _resolve_scope(
            settings.availability_check_scope, None, order.output_storage_location_id
        )

    shelves: dict[UUID | None, _Shelf] = {}
    for order in queue:
        scope = _scope(order)
        if scope not in shelves:
            shelves[scope] = _Shelf(StockPool(db, organization_id, scope))

    expected = _expected_output(queue, _scope)
    flats = await _explode_by_day(db, organization_id, queue, expected, shelves, _scope)

    # One stock read per scope and one template read for the whole queue, so
    # the cost grows with the number of scopes, not with the number of runs.
    children_by_scope: dict[UUID | None, set[UUID]] = {}
    for order, flat in zip(queue, flats, strict=True):
        if flat:
            children_by_scope.setdefault(_scope(order), set()).update(
                child_id for child_id, _qty, _unit, _uom in flat
            )
    for scope, children in children_by_scope.items():
        shelves[scope].left = await _get_available_stock_batch(
            db, organization_id, sorted(children), location_id=scope
        )
    all_children = sorted(set().union(*children_by_scope.values()))
    templates: dict[UUID, ProductTemplateDTO] = (
        await core_api.product_templates.get_many_async(
            db, organization_id, all_children
        )
        if all_children
        else {}
    )

    uom_cache: dict[UUID, UomDTO | None] = {}
    result: dict[UUID, PlanCoverage] = {}
    day_reached: tuple[bool, date] | None = None
    for order, flat in zip(queue, flats, strict=True):
        if planned_day(order) != day_reached:
            day_reached = planned_day(order)
            for scope, per_template in expected[day_reached].items():
                _add_expected(
                    shelves[scope].left,
                    per_template,
                    children_by_scope.get(scope, set()),
                )
        if not flat:
            continue
        shelf = shelves[_scope(order)]
        needs, line_uom_ids, legacy_units = _aggregate_needs(flat)

        shortages = await _shortages_from_needs(
            db,
            organization_id,
            needs=needs,
            line_uom_ids=line_uom_ids,
            legacy_units=legacy_units,
            stocks=shelf.left,
            templates=templates,
            uom_cache=uom_cache,
        )
        result[order.id] = PlanCoverage(_status(needs, shortages), shortages)

        # The run claims what it needs, in each ingredient's own stock unit,
        # so the next one in the queue is measured against what remains.
        for child_id, needed in needs.items():
            template = templates.get(child_id)
            claimed = await _in_stock_unit(
                db,
                organization_id,
                needed,
                line_uom_ids.get(child_id),
                template.uom_id if template else None,
                uom_cache,
            )
            if claimed is None:
                continue
            shelf.left[child_id] = max(
                Decimal('0'), shelf.left.get(child_id, Decimal('0')) - claimed
            )
    return result


async def _in_stock_unit(
    db: AsyncSession,
    organization_id: UUID,
    qty: Decimal,
    line_uom_id: UUID | None,
    stock_uom_id: UUID | None,
    uom_cache: dict[UUID, UomDTO | None],
) -> Decimal | None:
    """``qty`` in the ingredient's stock unit; ``None`` when no bridge exists."""
    if line_uom_id is None or stock_uom_id is None or line_uom_id == stock_uom_id:
        return qty
    units: list[UomDTO | None] = []
    for uom_id in (line_uom_id, stock_uom_id):
        if uom_id not in uom_cache:
            uom_cache[uom_id] = await core_api.uoms.get_async(
                db, uom_id, organization_id
            )
        units.append(uom_cache[uom_id])
    if units[0] is None or units[1] is None:
        return qty
    converted, ok = core_api.uoms.convert_quantity(qty, units[0], units[1])
    return converted if ok else None
