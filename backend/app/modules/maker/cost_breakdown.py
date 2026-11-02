"""Cost breakdown — per-ingredient cost contribution to a production run.

Returns ``CostBreakdownResponse`` with:
  - ``total_cost`` rounded to 2 decimal places
  - ``entries`` with per-ingredient cost and percentage-of-total
  - ``missing_cost_lines`` (template IDs) for ingredients that have no
    shared estimate (no priced layer or usable supplier offer)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cost_estimates import UnitCostEstimate
from app.core.money import quantise, quantise_or_none
from app.core.public_api import core_api

from . import bom_service
from ._schemas_breakdown import (
    CostBreakdownEntry,
    CostBreakdownPlannedDraw,
    CostBreakdownResponse,
)
from ._valuation_batch import fetch_estimates_batch
from .models import MakerRecipe


async def compute_breakdown(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    qty: Decimal,
    recipe_id: UUID | None = None,
) -> CostBreakdownResponse:
    """Resolve the multi-level BOM and compute per-ingredient cost & percentage.

    ``recipe_id`` picks a specific formula, the way completing a
    production order does. Without it the template's default formula
    answers — which is the right question for a catalogue estimate and
    the wrong one for an order built from a variant.

    The answer says which formula it is about (``recipe_state`` /
    ``recipe_id``): a product with no formula and a formula with no lines
    both cost zero entries, and the reader is sent to create the first and
    to fill the second — an answer that flattens them sends people to add
    ingredients to a formula that does not exist.
    """
    # The same resolution create_order makes, without its locks: the
    # explicit id refuses in the reader's language (a URL-edited id is how
    # a reader reaches that refusal), the default path answers None for a
    # product with no formula at all.
    recipe: MakerRecipe | None
    if recipe_id is not None:
        recipe = await bom_service.resolve_recipe(db, organization_id, recipe_id)
        resolved_recipe_id: UUID | None = recipe.id
    else:
        recipe = await bom_service.find_default_recipe(db, organization_id, template_id)
        resolved_recipe_id = recipe.id if recipe is not None else None

    output_template = await core_api.product_templates.get_async(
        db, organization_id, template_id
    )
    planned_uom = (
        await core_api.uoms.get_async(db, output_template.uom_id, organization_id)
        if output_template and output_template.uom_id
        else None
    )

    if recipe is None:
        return CostBreakdownResponse(
            output_template_id=template_id,
            planned_qty=qty,
            planned_uom_symbol=planned_uom.symbol if planned_uom else None,
            total_cost=quantise_or_none(Decimal('0')) or Decimal('0.00'),
            entries=[],
            missing_cost_lines=[],
            recipe_state='no_recipe',
            recipe_id=None,
        )

    # The same stock units the rates are held in, so a row's `unit_cost` x
    # `consumed_qty` adds up to its `cost` for the reader. The quantity is
    # shown in the unit it will actually leave the shelf in.
    flat = await bom_service.explode_in_stock_units(
        db, organization_id, template_id, qty, recipe_id=resolved_recipe_id
    )
    estimates = await fetch_estimates_batch(db, organization_id, flat)
    rates = {tid: estimate.unit_cost for tid, estimate in estimates.items()}

    # Batch-resolve ingredient display names (FE renders names, not UUIDs).
    child_ids = list(dict.fromkeys(child_id for child_id, _, _ in flat))
    template_map: dict[UUID, object] = {}
    template_names: dict[UUID, str | None] = {}
    if child_ids:
        templates = await core_api.product_templates.list_for_org_async(
            db, organization_id, limit=10_000
        )
        template_map = {t.id: t for t in templates}
        template_names = {t.id: t.name for t in templates}

    draws_by_line = await _plan_draws_by_line(db, organization_id, flat, template_map)

    rows: list[tuple[UUID, Decimal, str, Decimal | None]] = []
    missing: list[str] = []

    for child_id, child_qty, unit in flat:
        rate = rates.get(child_id)
        if rate is None:
            missing.append(str(child_id))
            rows.append((child_id, child_qty, unit, None))
        else:
            rows.append((child_id, child_qty, unit, rate * child_qty))

    total_cost = sum((c for _, _, _, c in rows if c is not None), Decimal('0'))

    entries: list[CostBreakdownEntry] = []
    for index, (child_id, child_qty, unit, cost) in enumerate(rows):
        pct: Decimal | None = None
        if cost is not None and total_cost > 0:
            pct = quantise_or_none(cost / total_cost * Decimal('100'))
        entries.append(
            CostBreakdownEntry(
                child_template_id=child_id,
                consumed_qty=child_qty,
                unit=unit,
                unit_cost=quantise_or_none(rates.get(child_id)),
                cost=quantise_or_none(cost) if cost is not None else None,
                percentage_of_total=pct,
                cost_source={
                    'layers': 'avco',
                    'supplier': 'supplier',
                    'unknown': 'none',
                }[estimates.get(child_id, UnitCostEstimate()).source],
                child_template_name=template_names.get(child_id),
                planned_draws=draws_by_line.get(index, []),
            )
        )

    return CostBreakdownResponse(
        output_template_id=template_id,
        planned_qty=qty,
        planned_uom_symbol=planned_uom.symbol if planned_uom else None,
        total_cost=quantise_or_none(total_cost) or Decimal('0.00'),
        entries=entries,
        missing_cost_lines=missing,
        recipe_state='empty' if not flat else 'has_lines',
        recipe_id=resolved_recipe_id,
    )


async def _plan_draws_by_line(
    db: AsyncSession,
    organization_id: UUID,
    flat: list[tuple[UUID, Decimal, str]],
    template_map: dict[UUID, object],
) -> dict[int, list[CostBreakdownPlannedDraw]]:
    """Where each line's draw would come from, shelf by shelf, before it runs.

    The plan is the one completion draws by — same candidates, same
    FIFO/FEFO order, ``any_owner`` like a run that consumes what stands on
    the shelf — read before anything leaves stock, so the draft's table can
    say which shelf the run will empty while closing it is still a choice.

    An ingredient the flat list names twice is drawn by one ordered plan
    over its whole need, walked line by line in the order the draw would
    fill them: two lines of one ingredient never promise the same shelf's
    stock twice. Takes from records that name no shelf are skipped — the
    closed run's lines render nothing for them either, and the planned
    table answers in the same silence.
    """
    needs: dict[UUID, Decimal] = {}
    for child_id, child_qty, _unit in flat:
        needs[child_id] = needs.get(child_id, Decimal('0')) + child_qty

    plans: dict[UUID, list[tuple[UUID, Decimal]]] = {}
    shelf_ids: set[UUID] = set()
    for child_id, need in needs.items():
        takes = await core_api.stock.plan_draw_async(
            db,
            organization_id,
            child_id,
            None,
            need,
            # The map holds DTOs that do not carry the field; a resolved
            # constant would be an override that beats the template's own
            # FEFO. Name a strategy only when the carrier carries one —
            # with none named, the plan follows the template itself.
            removal_strategy=getattr(
                template_map.get(child_id), 'removal_strategy', None
            ),
            any_owner=True,
        )
        per_shelf: dict[UUID, Decimal] = {}
        for take in takes:
            if take.location_id is None:
                continue
            per_shelf[take.location_id] = (
                per_shelf.get(take.location_id, Decimal('0')) + take.consumed
            )
        shelf_ids.update(per_shelf)
        plans[child_id] = list(per_shelf.items())

    names: dict[UUID, str | None] = {}
    for shelf_id in shelf_ids:
        location = await core_api.locations.get_async(db, organization_id, shelf_id)
        names[shelf_id] = location.name if location is not None else None

    draws_by_line: dict[int, list[CostBreakdownPlannedDraw]] = {}
    open_plans: dict[UUID, list[list[Any]]] = {}
    for index, (child_id, child_qty, _unit) in enumerate(flat):
        queue = open_plans.setdefault(
            child_id, [list(item) for item in plans.get(child_id, [])]
        )
        draws: list[CostBreakdownPlannedDraw] = []
        wanted = child_qty
        while wanted > 0 and queue:
            shelf_id, available = queue[0]
            take = min(available, wanted)
            draws.append(
                CostBreakdownPlannedDraw(
                    location_id=shelf_id,
                    location_name=names.get(shelf_id),
                    quantity=take,
                )
            )
            wanted -= take
            if take >= available:
                queue.pop(0)
            else:
                queue[0][1] = available - take
        # The plan takes what records hold, at whatever scale they hold
        # it ('8.000' beside '2.000000' from two shelves of one draw); the
        # moves ledger the reader compares against writes three places.
        draws_by_line[index] = [
            draw.model_copy(update={'quantity': quantise(draw.quantity, 3)})
            for draw in draws
        ]
    return draws_by_line
