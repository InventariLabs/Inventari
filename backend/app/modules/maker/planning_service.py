"""Planned runs measured against one shelf, one after another.

A draft's own availability check reads the shelf as if it were the only run
there. Two drafts that each need six of ten flour then both read as covered,
while together they need twelve. Planning reads the drafts as a queue: by
planned day, then by creation, each run counts only what the runs before it
left. A run with no planned day waits behind every dated one.

The queue is walked once (:func:`walk_plan`) and both of its readers read
that walk — the coverage of each run here and the combined list of needs in
``planning_needs`` — so the plan cannot call a run covered while the list
under it says its dough is missing. A run asks for what its formula names one
level deep (``bom_service.plan_needs``): a sub-assembly is taken from the
shelf, or from what draft runs of it make on the run's planned day or before
it. What neither covers is a sub-assembly to plan a run of, not raw materials
the run would quietly take: the flour belongs to the dough run.

This is a planning view, not completion's verdict. Completion judges the shelf
as it is when the run is closed (``availability_service``) and still makes a
missing sub-assembly inside the run from what the shelf holds; a draft that is
behind another in the queue is still completable while the shelf holds enough
for it alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import groupby
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

CoverageStatus = Literal['covered', 'partial', 'short']


@dataclass(frozen=True)
class PlanCoverage:
    """How far the shelf and the runs planned in time cover a run, after those before it.

    ``items`` are the ingredients that fall short, stated against what was
    left for this run — the same row shape the shortage list carries.
    """

    status: CoverageStatus
    items: list[ShortageItem] = field(default_factory=list)


@dataclass
class Claim:
    """What a run asks of one ingredient, and where it comes from.

    All in the ingredient's stock unit. ``needed`` is ``None`` when a line's
    unit has no bridge to the stock's: nothing is claimed then, and the
    readers name the ingredient instead of inventing a quantity.
    """

    template_id: UUID
    has_recipe: bool
    needed: Decimal | None
    #: The shelf of the run's scope just before the run took from it.
    on_shelf: Decimal
    from_shelf: Decimal = Decimal('0')
    #: What draft runs of the ingredient made on this run's day or before it.
    from_planned: Decimal = Decimal('0')

    @property
    def unmet(self) -> Decimal:
        if self.needed is None:
            return Decimal('0')
        return self.needed - self.from_shelf - self.from_planned


@dataclass
class QueuedRun:
    order: ProductionOrder
    scope: UUID | None
    #: The formula one level deep, in the lines' own units.
    needs: list[bom_service.DirectNeed]
    claims: list[Claim]


@dataclass
class PlanWalk:
    """Every draft in queue order, with what it took, and the catalogue read for it."""

    runs: list[QueuedRun] = field(default_factory=list)
    templates: dict[UUID, ProductTemplateDTO] = field(default_factory=dict)
    uoms: dict[UUID, UomDTO] = field(default_factory=dict)


class _Supply:
    """One availability scope: its shelf, and what planned runs have made so far."""

    def __init__(self, shelf: dict[UUID, Decimal]) -> None:
        self.shelf = shelf
        self.made: dict[UUID, Decimal] = {}

    def claim(
        self, template_id: UUID, has_recipe: bool, needed: Decimal | None
    ) -> Claim:
        """Take *needed* from the shelf first, then from what planned runs made."""
        on_shelf = self.shelf.get(template_id, Decimal('0'))
        claim = Claim(template_id, has_recipe, needed, on_shelf)
        if needed is None:
            return claim
        claim.from_shelf = max(Decimal('0'), min(needed, on_shelf))
        self.shelf[template_id] = on_shelf - claim.from_shelf
        made = self.made.get(template_id, Decimal('0'))
        claim.from_planned = min(needed - claim.from_shelf, made)
        self.made[template_id] = made - claim.from_planned
        return claim


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
    every dated one.
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


def _to_stock_unit(
    qty: Decimal,
    line_uom_id: UUID | None,
    stock_uom_id: UUID | None,
    uoms: dict[UUID, UomDTO],
) -> Decimal | None:
    """*qty* in the ingredient's stock unit; ``None`` when no bridge exists."""
    if line_uom_id is None or stock_uom_id is None or line_uom_id == stock_uom_id:
        return qty
    source, target = uoms.get(line_uom_id), uoms.get(stock_uom_id)
    if source is None or target is None:
        return qty
    converted, ok = core_api.uoms.convert_quantity(qty, source, target)
    return converted if ok else None


def _asked(
    needs: list[bom_service.DirectNeed],
    templates: dict[UUID, ProductTemplateDTO],
    uoms: dict[UUID, UomDTO],
) -> dict[UUID, tuple[bool, Decimal | None]]:
    """Per ingredient, whether it has a recipe and what the run asks in its stock unit."""
    asked: dict[UUID, tuple[bool, Decimal | None]] = {}
    for need in needs:
        template = templates.get(need.child_template_id)
        qty = _to_stock_unit(
            need.qty, need.uom_id, template.uom_id if template else None, uoms
        )
        has_recipe, total = asked.get(need.child_template_id, (False, Decimal('0')))
        asked[need.child_template_id] = (
            has_recipe or need.has_recipe,
            None if total is None or qty is None else total + qty,
        )
    return asked


async def walk_plan(db: AsyncSession, organization_id: UUID) -> PlanWalk:
    """Walk the draft runs one planned day at a time, each claiming what it asks.

    Each availability scope (the whole organization, or a run's own output
    shelf under PER_LOCATION) has its own shelf. When the walk reaches a day,
    what that day's runs make goes on the scope of the run that makes it, so
    it serves the runs of that day — whatever order they were created in —
    and of the days after it, never the runs before it. A run then takes each
    ingredient from the shelf first and from what planned runs made after
    that. Drafts whose recipe yields nothing to scale a plan by are left out.
    """
    drafts = await queued_drafts(db, organization_id)
    if not drafts:
        return PlanWalk()
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
        return PlanWalk()

    settings = await recipe_service.get_settings(db, organization_id, for_update=False)
    scopes = [
        _resolve_scope(
            settings.availability_check_scope, None, o.output_storage_location_id
        )
        for o in queue
    ]
    run_needs = [
        needs or []
        for needs in await bom_service.plan_needs(
            db,
            organization_id,
            [(o.recipe_id, o.planned_qty) for o in queue if o.recipe_id is not None],
        )
    ]

    # One stock read per scope and one template read for the whole queue, so
    # the cost grows with the number of scopes, not with the number of runs.
    children_by_scope: dict[UUID | None, set[UUID]] = {scope: set() for scope in scopes}
    for scope, needs in zip(scopes, run_needs, strict=True):
        children_by_scope[scope].update(n.child_template_id for n in needs)
    supplies = {
        scope: _Supply(
            await _get_available_stock_batch(
                db, organization_id, sorted(children), location_id=scope
            )
            if children
            else {}
        )
        for scope, children in children_by_scope.items()
    }
    all_children = sorted(set().union(*children_by_scope.values()))
    walk = PlanWalk(
        templates=(
            await core_api.product_templates.get_many_async(
                db, organization_id, all_children
            )
            if all_children
            else {}
        ),
        uoms={
            u.id: u for u in await core_api.uoms.list_for_org_async(db, organization_id)
        },
    )

    runs = list(zip(queue, scopes, run_needs, strict=True))
    for _day, day_runs in groupby(runs, key=lambda run: planned_day(run[0])):
        today = list(day_runs)
        for order, scope, _needs in today:
            made = supplies[scope].made
            made[order.output_template_id] = (
                made.get(order.output_template_id, Decimal('0')) + order.planned_qty
            )
        for order, scope, needs in today:
            walk.runs.append(
                QueuedRun(
                    order,
                    scope,
                    needs,
                    [
                        supplies[scope].claim(template_id, has_recipe, needed)
                        for template_id, (has_recipe, needed) in _asked(
                            needs, walk.templates, walk.uoms
                        ).items()
                    ],
                )
            )
    return walk


async def coverage_for_drafts(
    db: AsyncSession, organization_id: UUID
) -> dict[UUID, PlanCoverage]:
    """The coverage of every draft run that has a recipe to measure.

    Read off the one walk of the queue (:func:`walk_plan`). Drafts without a
    recipe, with an empty formula or with a yield that cannot scale a plan
    have nothing to forecast and get no entry.
    """
    walk = await walk_plan(db, organization_id)
    uom_cache: dict[UUID, UomDTO | None] = dict(walk.uoms)
    result: dict[UUID, PlanCoverage] = {}
    for run in walk.runs:
        if not run.needs:
            continue
        needs, line_uom_ids, legacy_units = _aggregate_needs(
            [(n.child_template_id, n.qty, n.unit, n.uom_id) for n in run.needs]
        )
        short = {
            c.template_id: c for c in run.claims if c.needed is None or c.unmet > 0
        }
        # What the run got (or, unmeasured, what the shelf held), against what
        # it asks: the shortage rows of the shortage list, from the same rule.
        shortages = await _shortages_from_needs(
            db,
            organization_id,
            needs={tid: qty for tid, qty in needs.items() if tid in short},
            line_uom_ids=line_uom_ids,
            legacy_units=legacy_units,
            stocks={
                tid: (c.on_shelf if c.needed is None else c.from_shelf + c.from_planned)
                for tid, c in short.items()
            },
            templates=walk.templates,
            uom_cache=uom_cache,
        )
        result[run.order.id] = PlanCoverage(_status(needs, shortages), shortages)
    return result
