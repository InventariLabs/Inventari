"""Which batches a run takes its ingredients from — shown first, then chosen.

Before a run closes the person sees, ingredient by ingredient, the batches the
draw will take — the product's removal order, earliest best-before first under
FEFO — and may name others: from a list, or by scanning a batch label. The
plan is Core's own (``plan_draw_async``), asked at the scope the run draws
under, so what the page shows is what the taking call would take; held,
recalled and expired batches are not candidates there, so they are not
offered here either.

A choice is binding. The run takes exactly the batches chosen, in the
quantities chosen; a choice that does not add up to what the run takes of the
ingredient, or that names a batch which cannot give what was chosen, is
refused before anything leaves a shelf. The movements the run writes name
each batch, which is what the batch record and a recall read.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import QuantConsumptionDTO, StockLotDTO
from app.core.exceptions import ServiceRejectionError
from app.core.money import quantise
from app.core.public_api import core_api

from . import bom_service
from ._schemas_batches import (
    IngredientBatchDraw,
    IngredientBatchOption,
    IngredientBatchPlan,
    IngredientLotChoice,
)

#: The places a quantity is compared to: the precision the run's lines keep.
_PLACES = 4

#: An ingredient's chosen draw: (batch, quantity) parts, taken in order.
ChosenParts = dict[UUID, deque[tuple[UUID, Decimal]]]


def needs_per_ingredient(flat: list[tuple[UUID, Decimal, str]]) -> dict[UUID, Decimal]:
    """What the run takes of each ingredient, summed over the flat list."""
    needs: dict[UUID, Decimal] = {}
    for child_id, qty, _unit in flat:
        needs[child_id] = needs.get(child_id, Decimal('0')) + qty
    return needs


async def _names_and_units(
    db: AsyncSession, organization_id: UUID, template_ids: list[UUID]
) -> tuple[dict[UUID, str], dict[UUID, str | None]]:
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, template_ids
    )
    symbols = {
        uom.id: uom.symbol
        for uom in await core_api.uoms.list_for_org_async(db, organization_id)
    }
    names = {tid: tpl.name for tid, tpl in templates.items()}
    units = {
        tid: symbols.get(tpl.uom_id) if tpl.uom_id else None
        for tid, tpl in templates.items()
    }
    return names, units


async def plan_ingredient_batches(
    db: AsyncSession,
    organization_id: UUID,
    output_template_id: UUID,
    planned_qty: Decimal,
    *,
    recipe_id: UUID | None,
    location_id: UUID | None,
) -> list[IngredientBatchPlan]:
    """Per ingredient: what the run needs, the draw it makes, the batches it may take.

    *location_id* is the resolved scope the run draws under (None: every
    shelf). A recipe with no ingredients plans nothing.
    """
    flat = await bom_service.explode_in_stock_units(
        db, organization_id, output_template_id, planned_qty, recipe_id=recipe_id
    )
    needs = needs_per_ingredient(flat)
    names, units = await _names_and_units(db, organization_id, list(needs))
    plans: list[IngredientBatchPlan] = []
    for child_id, need in needs.items():
        lots = {
            lot.id: lot
            for lot in await core_api.stock.list_lots_async(
                db, organization_id, child_id
            )
        }
        draw = await core_api.stock.plan_draw_async(
            db, organization_id, child_id, location_id, need, any_owner=True
        )
        free = await core_api.stock.plan_draw_async(
            db, organization_id, child_id, location_id, None, any_owner=True
        )
        plans.append(
            IngredientBatchPlan(
                template_id=child_id,
                template_name=names.get(child_id),
                uom_symbol=units.get(child_id),
                needed=quantise(need, _PLACES),
                plan=_drawn_by_batch(draw, lots),
                batches=_free_by_batch(free, lots),
            )
        )
    return plans


def _drawn_by_batch(
    draw: list[QuantConsumptionDTO], lots: dict[UUID, StockLotDTO]
) -> list[IngredientBatchDraw]:
    """The plan's parts summed per batch, in the order first drawn on."""
    totals: dict[UUID | None, Decimal] = {}
    for part in draw:
        totals[part.lot_id] = totals.get(part.lot_id, Decimal('0')) + part.consumed
    rows: list[IngredientBatchDraw] = []
    for lot_id, quantity in totals.items():
        lot = lots.get(lot_id) if lot_id is not None else None
        rows.append(
            IngredientBatchDraw(
                lot_id=lot_id,
                lot_name=lot.name if lot else None,
                expiry_date=(lot.expiry_date or lot.use_by_date) if lot else None,
                quantity=quantise(quantity, _PLACES),
            )
        )
    return rows


def _free_by_batch(
    free: list[QuantConsumptionDTO], lots: dict[UUID, StockLotDTO]
) -> list[IngredientBatchOption]:
    """Every batch with stock free to take, earliest best-before first."""
    totals: dict[UUID, Decimal] = {}
    for part in free:
        if part.lot_id is not None:
            totals[part.lot_id] = totals.get(part.lot_id, Decimal('0')) + part.consumed
    options = [
        IngredientBatchOption(
            lot_id=lot_id,
            lot_name=lots[lot_id].name,
            expiry_date=lots[lot_id].expiry_date or lots[lot_id].use_by_date,
            production_date=lots[lot_id].production_date,
            available=quantise(available, _PLACES),
        )
        for lot_id, available in totals.items()
        if lot_id in lots and available > 0
    ]
    options.sort(key=lambda o: (o.expiry_date is None, o.expiry_date, o.lot_name))
    return options


@dataclass(frozen=True)
class _Named:
    names: dict[UUID, str]
    lot_names: dict[UUID, str]
    #: Batch -> the product it is a batch of.
    lot_products: dict[UUID, UUID]

    def ingredient(self, template_id: UUID) -> str:
        return self.names.get(template_id) or str(template_id)

    def batch(self, lot_id: UUID) -> str:
        return self.lot_names.get(lot_id) or str(lot_id)


async def resolve_choices(
    db: AsyncSession,
    organization_id: UUID,
    flat: list[tuple[UUID, Decimal, str]],
    choices: list[IngredientLotChoice],
    location_id: UUID | None,
    *,
    record_shortfall: bool,
) -> ChosenParts:
    """Check the person's batch choices against the run and order them per ingredient.

    Refused, before anything is drawn: a choice for something the run does
    not take; choices of an ingredient that do not add up to what the run
    takes of it (compared at the precision the run's lines keep — the last
    part absorbs what lies below it, so the run takes its need exactly);
    and, for a run being completed, a batch that cannot give what was chosen
    of it at the scope the run draws under. A run recorded after the fact
    takes what a chosen batch has and records the rest as the line's
    shortfall, as it does for an ingredient nobody chose a batch for.
    """
    if not choices:
        return {}
    needs = needs_per_ingredient(flat)
    named = await _naming(db, organization_id, choices)
    parts: ChosenParts = {}
    for choice in choices:
        if choice.template_id not in needs:
            raise ServiceRejectionError(
                'production_batch_not_an_ingredient',
                ingredient=named.ingredient(choice.template_id),
            )
        if named.lot_products.get(choice.lot_id) != choice.template_id:
            raise ServiceRejectionError(
                'production_batch_of_another_product',
                batch=named.batch(choice.lot_id),
                ingredient=named.ingredient(choice.template_id),
            )
        parts.setdefault(choice.template_id, deque()).append(
            (choice.lot_id, choice.quantity)
        )
    for template_id, queue in parts.items():
        need = needs[template_id]
        chosen = sum((qty for _lot, qty in queue), Decimal('0'))
        if quantise(chosen, _PLACES) != quantise(need, _PLACES):
            raise ServiceRejectionError(
                'production_batch_choice_mismatch',
                ingredient=named.ingredient(template_id),
                chosen=_shown(chosen),
                needed=_shown(need),
            )
        last_lot, last_qty = queue.pop()
        queue.append((last_lot, last_qty + need - chosen))
        if not record_shortfall:
            await _refuse_a_short_batch(
                db, organization_id, template_id, queue, location_id, named
            )
    return parts


async def _refuse_a_short_batch(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    queue: deque[tuple[UUID, Decimal]],
    location_id: UUID | None,
    named: _Named,
) -> None:
    per_lot: dict[UUID, Decimal] = {}
    for lot_id, qty in queue:
        per_lot[lot_id] = per_lot.get(lot_id, Decimal('0')) + qty
    for lot_id, wanted in per_lot.items():
        free = await free_in_batch(
            db, organization_id, template_id, lot_id, location_id
        )
        if free < wanted:
            raise ServiceRejectionError(
                'production_batch_short',
                batch=named.batch(lot_id),
                ingredient=named.ingredient(template_id),
                available=_shown(free),
                chosen=_shown(wanted),
            )


async def free_in_batch(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    lot_id: UUID,
    location_id: UUID | None,
) -> Decimal:
    """What one batch of an ingredient has free to take, at the run's scope.

    A held batch has nothing free: the plan does not count it.
    """
    draw = await core_api.stock.plan_draw_async(
        db,
        organization_id,
        template_id,
        location_id,
        None,
        any_owner=True,
        lot_id=lot_id,
    )
    return sum((part.consumed for part in draw), Decimal('0'))


def parts_for_line(
    chosen: ChosenParts, template_id: UUID, qty: Decimal
) -> list[tuple[UUID | None, Decimal]]:
    """The batches one line of the flat list is taken from.

    An ingredient nobody chose for is one part with no batch named — the
    removal order decides. A chosen one takes its line's quantity off the
    front of its choices, so an ingredient that appears on two lines (once
    directly, once through a sub-assembly) spends its choices once.
    """
    queue = chosen.get(template_id)
    if queue is None:
        return [(None, qty)]
    taken: list[tuple[UUID | None, Decimal]] = []
    left = qty
    while left > 0 and queue:
        lot_id, available = queue.popleft()
        part = min(available, left)
        taken.append((lot_id, part))
        left -= part
        if available > part:
            queue.appendleft((lot_id, available - part))
    return taken


async def _naming(
    db: AsyncSession, organization_id: UUID, choices: list[IngredientLotChoice]
) -> _Named:
    template_ids = list({c.template_id for c in choices})
    names, _units = await _names_and_units(db, organization_id, template_ids)
    lot_names: dict[UUID, str] = {}
    lot_products: dict[UUID, UUID] = {}
    for template_id in template_ids:
        for lot in await core_api.stock.list_lots_async(
            db, organization_id, template_id
        ):
            lot_names[lot.id] = lot.name
            lot_products[lot.id] = lot.product_template_id
    return _Named(names, lot_names, lot_products)


def _shown(qty: Decimal) -> str:
    """A quantity for a sentence: no trailing zeros, no exponent."""
    text = format(quantise(qty, _PLACES).normalize(), 'f')
    return text
