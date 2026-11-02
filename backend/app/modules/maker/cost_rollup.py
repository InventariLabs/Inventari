"""Cost rollup — total input cost of a multi-level BOM at a given qty."""

from __future__ import annotations

from dataclasses import dataclass
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
    for child_id, child_qty, _unit in flat:
        rate = rates.get(child_id, UnitCostEstimate()).unit_cost
        if rate is None:
            unrated += 1
        else:
            total += rate * child_qty
    return CostRollup(total=total, ingredient_count=len(flat), unrated_count=unrated)


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
