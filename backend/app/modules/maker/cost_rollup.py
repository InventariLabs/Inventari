"""Cost rollup — total input cost of a multi-level BOM at a given qty."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cost_estimates import UnitCostEstimate
from app.core.public_api import core_api

from . import bom_service
from ._valuation_batch import fetch_estimates_batch
from .models import MakerRecipe


@dataclass(frozen=True)
class CostRollup:
    """What a bill of materials costs, and what the total is made of.

    A zero ``total`` answers two different questions — "the formula
    lists nothing" and "it lists ingredients nobody has priced yet" —
    and a caller that shows the figure to somebody has to tell them
    apart. The counts travel with the sum so it does not have to guess.
    """

    total: Decimal
    ingredient_count: int
    unrated_count: int
    #: Which answer priced each ingredient — 'layers', 'supplier', 'typed' or
    #: 'unknown'. A caller showing a fallback price needs to know whether the
    #: estimate actually reached it.
    sources: dict[UUID, str] = field(default_factory=dict)


async def compute_cost_rollup(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    qty: Decimal,
    recipe_id: UUID | None = None,
) -> CostRollup:
    """Sum shared estimated stock-unit costs over the exploded BOM.

    ``recipe_id`` picks a formula, the way ``cost_breakdown`` does. Without
    one the template's default answers, which is the right question for a
    catalogue estimate and the wrong one for a specific variant.
    """
    # In the ingredients' own stock units, because the rates below are held
    # per stock unit: a line reading 500 g against a rate per kilogram was
    # multiplied as though it read 500 kg, so the preview and the run
    # disagreed by the factor between the two units.
    flat = await bom_service.explode_in_stock_units(
        db, organization_id, template_id, qty, recipe_id=recipe_id
    )
    rates = await fetch_estimates_batch(db, organization_id, flat)
    return _rollup_from_flat(flat, rates)


async def compute_cost_rollups_for_recipes(
    db: AsyncSession,
    organization_id: UUID,
    requests: list[tuple[MakerRecipe, Decimal]],
) -> dict[UUID, CostRollup]:
    """Batched :func:`compute_cost_rollup` for a page of recipes.

    The per-recipe call pays the explosion, the unit catalogue, the
    ingredient templates and the rates for one recipe at a time — a
    catalogue of never-run recipes paid all of it per row and the page's
    query count grew with the page. The batch shares every lookup across
    the page; the arithmetic stays per recipe.
    """
    exploded = await bom_service.explode_recipes_in_stock_units(
        db, organization_id, requests
    )
    leaf_ids = sorted({cid for flat in exploded.values() for (cid, *_rest) in flat})
    rates = (
        await core_api.valuation.estimate_unit_cost_async(db, organization_id, leaf_ids)
        if leaf_ids
        else {}
    )
    return {
        recipe_id: _rollup_from_flat(flat, rates)
        for recipe_id, flat in exploded.items()
    }


def _rollup_from_flat(
    flat: list[tuple[UUID, Decimal, str]],
    rates: dict[UUID, UnitCostEstimate],
) -> CostRollup:
    total = Decimal('0')
    unrated = 0
    sources: dict[UUID, str] = {}
    for child_id, child_qty, _unit in flat:
        estimate = rates.get(child_id, UnitCostEstimate())
        sources[child_id] = estimate.source
        if estimate.unit_cost is None:
            unrated += 1
        else:
            total += estimate.unit_cost * child_qty
    return CostRollup(
        total=total,
        ingredient_count=len(flat),
        unrated_count=unrated,
        sources=sources,
    )


async def compute_total_cost(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    qty: Decimal,
    recipe_id: UUID | None = None,
) -> Decimal:
    """Sum shared estimated stock-unit costs over the exploded BOM.

    Ingredients with no valuation rate (``None``) contribute zero — they
    show up in ``cost_breakdown.missing_cost_lines`` for the caller.
    """
    rollup = await compute_cost_rollup(db, organization_id, template_id, qty, recipe_id)
    return rollup.total


async def compute_unit_cost(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    planned_qty: Decimal,
    recipe_id: UUID | None = None,
) -> Decimal:
    """Cost per produced unit, clamped to 0 if the BOM has no rateable inputs.

    Used for forecasts; a production receipt uses consumed FIFO layers.
    Yields ``Decimal('0')`` when ``planned_qty`` is zero.
    """
    if planned_qty <= 0:
        return Decimal('0')
    total = await compute_total_cost(
        db, organization_id, template_id, planned_qty, recipe_id
    )
    return total / planned_qty if total > 0 else Decimal('0')


def process_minutes(recipe: MakerRecipe) -> Decimal:
    """How long the formula's steps take, in minutes.

    A step saved before steps carried durations has no time and adds none.
    """
    total = Decimal('0')
    for step in recipe.process_steps or []:
        if not isinstance(step, dict):
            continue
        minutes = step.get('minutes')
        if minutes is not None:
            total += Decimal(str(minutes))
    return total


def labour_cost_per_batch(recipe: MakerRecipe, hourly_rate: Decimal | None) -> Decimal:
    """The batch's own labour: its steps' time at the organization's rate.

    Zero is a real answer — nobody timed the steps, or nobody named a rate.
    The caller shows the line only when it is above zero, so an untimed
    formula does not claim its labour was free.
    """
    if hourly_rate is None or hourly_rate <= 0:
        return Decimal('0')
    minutes = process_minutes(recipe)
    if minutes <= 0:
        return Decimal('0')
    from app.core.money import quantise

    return quantise(minutes / Decimal('60') * hourly_rate, 2)


def fixed_cost_per_batch(recipe: MakerRecipe) -> Decimal:
    """The fixed cost lines of one batch, summed."""
    return sum((line.amount for line in recipe.cost_lines), Decimal('0'))
