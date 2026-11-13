"""Availability check service — computes ingredient availability for production.

before clicking "produce", the user knows whether they can afford
the batch. This service:

1. Explodes a recipe into its flat leaf requirements (reusing
   ``explode_by_recipe_with_uom``)
   for **1 batch** — this gives per-batch needs regardless of the requested
   ``batches`` parameter.
2. Queries available stock (``available_quantity = quantity - reserved_quantity``)
   per leaf template, optionally scoped to a single location.
3. Attempts UoM conversion when the recipe line and the stock use different
   units in the same dimension (e.g. recipe in kg, stock in g).
4. Computes ``max_batches`` — the largest number of complete batches the
   current stock can support (bottleneck ingredient) — and a per-ingredient
   shortage list.

Returned data shapes are consumed by:
- ``GET /maker/recipes/{id}/availability`` endpoint (catalog badge + detail tab)
- ``create_order`` shortage strategy enforcement (ALLOW/WARN/BLOCK)
- ``complete_production`` actionable 422 shortage list
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ProductTemplateDTO, UomDTO
from app.core.exceptions import EntityNotFoundError
from app.core.public_api import core_api

from . import bom_service, recipe_service
from .models import MakerRecipe

if TYPE_CHECKING:
    from .models import ProductionOrder


@dataclass(frozen=True)
class IngredientAvailability:
    """Per-ingredient availability result.

    ``needed`` is stated in the recipe's unit (``uom_symbol``). ``available``
    is stated in the recipe's unit too — except when the two measures have no
    bridge, and then it is the raw stock in its own unit
    (``available_uom_symbol``) and ``shortage`` is ``None``: with nothing
    saying how litres relate to kilograms, no verdict exists to report.
    """

    child_template_id: UUID
    child_template_name: str | None
    needed: Decimal
    available: Decimal
    shortage: Decimal | None  # max(0, needed - available); None = unknown
    uom_symbol: str | None
    convertible: bool
    available_uom_symbol: str | None = None
    # What buying the shortfall asks for: the shortage put on the
    # ingredient's own stock unit's step, up, and stated in that unit — the
    # quantity a shopping list line will carry. None when nothing is short,
    # or when the measures have no bridge and so have no quantity to buy.
    to_buy: Decimal | None = None
    to_buy_uom_symbol: str | None = None


@dataclass(frozen=True)
class AvailabilityResult:
    """Aggregated availability check for a recipe.

    ``max_batches`` is ``None`` when at least one ingredient cannot be
    compared — a bottleneck that cannot be measured does not produce a
    number of batches.
    """

    max_batches: Decimal | None
    ingredients: list[IngredientAvailability]
    has_shortage: bool
    has_unknown: bool = False


@dataclass(frozen=True)
class ShortageItem:
    """One ingredient in a shortage list (used by create/complete flows).

    ``shortage`` is ``None`` when the measures cannot meet: the ingredient
    still stops the order, but as "nobody can tell", not as a quantity.
    """

    child_template_id: UUID
    child_template_name: str | None
    needed: Decimal
    available: Decimal
    shortage: Decimal | None
    uom_symbol: str | None
    convertible: bool = True
    available_uom_symbol: str | None = None


async def _get_available_stock_batch(
    db: AsyncSession,
    organization_id: UUID,
    template_ids: list[UUID],
    *,
    location_id: UUID | None = None,
) -> dict[UUID, Decimal]:
    """Sum ``available_quantity`` per template in one query.

    Batch twin of the former per-template ``get_available_stock``:
    ``available = quantity - reserved_quantity`` per quant of the records'
    view (``core_api.stock.list_quants_async``).
    When ``location_id`` is None, sums across all locations (GLOBAL scope).
    """
    if not template_ids:
        return {}
    quants = await core_api.stock.list_quants_async(
        db,
        organization_id,
        storage_location_id=location_id,
        product_template_ids=template_ids,
    )
    totals: dict[UUID, Decimal] = {}
    for q in quants:
        if q.available_quantity > 0:
            totals[q.product_template_id] = (
                totals.get(q.product_template_id, Decimal('0')) + q.available_quantity
            )
    return totals


@dataclass(frozen=True)
class _MeasuredStock:
    """Stock per leaf template, restated in the recipe's measure where possible."""

    converted: dict[UUID, Decimal]
    convertibles: dict[UUID, bool]
    stock_uom_symbols: dict[UUID, str | None]
    max_batches: Decimal | None
    has_unknown: bool


def _line_unit_symbol(
    recipe_uom: UomDTO | None,
    stock_symbol: str | None,
    legacy_unit: str | None,
) -> str | None:
    """The unit a line's needed quantity is counted in.

    Its own unit when it names one. A line that names none is counted in its
    ingredient's stock unit — the unit its stock move uses — and only a
    product without a unit either falls back to the line's free text.
    """
    if recipe_uom is not None:
        return recipe_uom.symbol
    return stock_symbol or legacy_unit


async def _measure_stock_against_recipe(
    db: AsyncSession,
    *,
    per_batch_needs: dict[UUID, Decimal],
    line_uom_ids: dict[UUID, UUID | None],
    template_cache: dict[UUID, ProductTemplateDTO | None],
    get_uom: Callable[[UUID | None], Awaitable[UomDTO | None]],
    raw_stocks: dict[UUID, Decimal],
) -> _MeasuredStock:
    """Convert each leaf's stock into the recipe's unit and find the bottleneck.

    An ingredient whose measures have no bridge contributes no batch count:
    dividing a litre count by a kilogram requirement is how "0.002 batches"
    was born. It is reported as unknown instead.

    ``raw_stocks`` maps each leaf template to its total available stock
    (pre-fetched in one query by the caller).
    """
    converted_stocks: dict[UUID, Decimal] = {}
    convertibles: dict[UUID, bool] = {}
    stock_uom_symbols: dict[UUID, str | None] = {}
    max_batches: Decimal | None = None

    for child_id, per_batch in per_batch_needs.items():
        if per_batch <= 0:
            continue

        raw_stock = raw_stocks.get(child_id, Decimal('0'))
        recipe_uom = await get_uom(line_uom_ids.get(child_id))
        template = template_cache.get(child_id)
        stock_uom = await get_uom(template.uom_id if template else None)

        converted = raw_stock
        convertible = True
        if recipe_uom is not None and stock_uom is not None:
            if recipe_uom.id != stock_uom.id:
                converted, convertible = core_api.uoms.convert_quantity(
                    raw_stock, stock_uom, recipe_uom
                )

        converted_stocks[child_id] = converted
        convertibles[child_id] = convertible
        stock_uom_symbols[child_id] = stock_uom.symbol if stock_uom else None

        if not convertible:
            continue
        # A batch is a thing you either make or do not, so this is floored
        # rather than quantised: the screen used to offer "568.1818 batches"
        # of a tray bake. Never below zero — stock reserved past what is on
        # hand is "none", not a negative number of batches. Quantised, because
        # a division keeps the exponent it landed on and ten batches went out
        # on the wire as "1E+1".
        ingredient_max = max(
            Decimal('0'),
            (converted / per_batch).quantize(Decimal('1'), rounding=ROUND_FLOOR),
        )
        if max_batches is None or ingredient_max < max_batches:
            max_batches = ingredient_max

    has_unknown = not all(convertibles.values())
    return _MeasuredStock(
        converted=converted_stocks,
        convertibles=convertibles,
        stock_uom_symbols=stock_uom_symbols,
        max_batches=max_batches
        if max_batches is not None or has_unknown
        else Decimal('0'),
        has_unknown=has_unknown,
    )


async def compute_availability(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    *,
    batches: Decimal | None = None,
    planned_qty: Decimal | None = None,
    location_id: UUID | None = None,
) -> AvailabilityResult:
    """Check ingredient availability for producing ``batches`` of a recipe.

    Parameters
    ----------
    batches
        Number of batches to check. If None, computes ``max_batches`` only
        (each ingredient shows stock as ``available``, ``needed=0``).
    planned_qty
        The output quantity to check, instead of ``batches``. The recipe is
        exploded at this quantity, so 5 planned against a yield of 3 is
        exactly 5 pieces of a 3-piece line at any depth, where 5 / 3 batches
        times 3 is a trillionth over.
    location_id
        If set, check stock only at this location. Otherwise check globally.

    Returns
    -------
    AvailabilityResult with per-ingredient detail and ``max_batches``.
    """
    recipe = await recipe_service.get_recipe(db, organization_id, recipe_id)
    if recipe is None:
        raise EntityNotFoundError('maker_recipe', f'Recipe {recipe_id} not found')

    # Explode for 1 batch to get per-batch needs (works regardless of
    # the requested batch count). The detailed explode keeps each leaf's
    # line ``uom_id`` — including leaves reached through nested
    # sub-assemblies — so UoM conversion works at any depth.
    one_batch_flat = await bom_service.explode_by_recipe_with_uom(
        db, organization_id, recipe_id, recipe.batch_yield_qty
    )

    if not one_batch_flat:
        return AvailabilityResult(
            max_batches=Decimal('0'),
            ingredients=[],
            has_shortage=False,
        )

    # Aggregate per-batch needs per template (explode can produce duplicates
    # via different sub-assembly paths). Keep the line UoM + legacy unit
    # string per leaf for conversion and display.
    per_batch_needs: dict[UUID, Decimal] = {}
    line_uom_ids: dict[UUID, UUID | None] = {}
    legacy_units: dict[UUID, str | None] = {}
    for child_id, child_qty, unit, line_uom_id in one_batch_flat:
        per_batch_needs[child_id] = (
            per_batch_needs.get(child_id, Decimal('0')) + child_qty
        )
        if child_id not in line_uom_ids or line_uom_ids[child_id] is None:
            line_uom_ids[child_id] = line_uom_id
        legacy_units.setdefault(child_id, unit or None)

    # Batch-load UoM objects and templates for conversion.
    uom_cache: dict[UUID, UomDTO | None] = {}

    async def _get_uom(uom_id: UUID | None) -> UomDTO | None:
        if uom_id is None:
            return None
        if uom_id not in uom_cache:
            uom_cache[uom_id] = await core_api.uoms.get_async(
                db, uom_id, organization_id
            )
        return uom_cache[uom_id]

    # Fetch templates and stock in batch — a query per ingredient made the
    # check cost grow with the size of the recipe.
    template_cache: dict[UUID, ProductTemplateDTO | None] = dict(
        await core_api.product_templates.get_many_async(
            db, organization_id, list(per_batch_needs)
        )
    )
    raw_stocks = await _get_available_stock_batch(
        db, organization_id, list(per_batch_needs), location_id=location_id
    )

    stock = await _measure_stock_against_recipe(
        db,
        per_batch_needs=per_batch_needs,
        line_uom_ids=line_uom_ids,
        template_cache=template_cache,
        get_uom=_get_uom,
        raw_stocks=raw_stocks,
    )
    converted_stocks = stock.converted
    convertibles = stock.convertibles
    stock_uom_symbols = stock.stock_uom_symbols
    max_batches = stock.max_batches
    has_unknown = stock.has_unknown

    # A plan is exploded at its own quantity: a sub-assembly whose yield does
    # not divide the plan has a per-batch need that is already rounded, and
    # scaling it back is a trillionth over exactly what the stock holds. The
    # one-batch explosion above stays for ``max_batches`` and for a batch count.
    planned_needs: dict[UUID, Decimal] | None = None
    if planned_qty is not None:
        planned_needs, _uom_ids, _units = _aggregate_needs(
            await bom_service.explode_by_recipe_with_uom(
                db, organization_id, recipe_id, planned_qty
            )
        )

    # Build ingredient list.
    requested_batches = batches if batches is not None else Decimal('0')
    ingredients: list[IngredientAvailability] = []
    for child_id, per_batch in per_batch_needs.items():
        needed = (
            planned_needs.get(child_id, Decimal('0'))
            if planned_needs is not None
            else per_batch * requested_batches
        )
        available = converted_stocks.get(child_id, Decimal('0'))
        convertible = convertibles.get(child_id, True)
        shortage = max(Decimal('0'), needed - available) if convertible else None

        recipe_uom = await _get_uom(line_uom_ids.get(child_id))
        template = template_cache.get(child_id)
        stock_uom = await _get_uom(template.uom_id if template else None)

        # The shopping list is shopped in the ingredient's stock unit, and a
        # requirement is put on the next step at or above it — needing part of
        # a piece is needing the piece. The same rule the list's own write
        # takes, so the button that fills the list states what it will hold.
        to_buy: Decimal | None = None
        if shortage is not None and shortage > 0:
            missing: Decimal | None = shortage
            if (
                recipe_uom is not None
                and stock_uom is not None
                and recipe_uom.id != stock_uom.id
            ):
                missing, ok = core_api.uoms.convert_quantity(
                    shortage, recipe_uom, stock_uom
                )
                if not ok:
                    missing = None
            if missing is not None:
                to_buy = core_api.uoms.round_up(missing, stock_uom)

        ingredients.append(
            IngredientAvailability(
                child_template_id=child_id,
                child_template_name=template.name if template else None,
                needed=needed,
                available=available,
                shortage=shortage,
                uom_symbol=_line_unit_symbol(
                    recipe_uom,
                    stock_uom_symbols.get(child_id),
                    legacy_units.get(child_id),
                ),
                convertible=convertible,
                available_uom_symbol=stock_uom_symbols.get(child_id)
                if not convertible
                else None,
                to_buy=to_buy,
                to_buy_uom_symbol=stock_uom.symbol if stock_uom else None,
            )
        )

    has_shortage = any(
        ing.shortage is not None and ing.shortage > 0 for ing in ingredients
    )

    return AvailabilityResult(
        max_batches=max_batches,
        ingredients=ingredients,
        has_shortage=has_shortage,
        has_unknown=has_unknown,
    )


async def compute_shortage_list(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    planned_qty: Decimal,
    *,
    location_id: UUID | None = None,
) -> list[ShortageItem]:
    """Return only ingredients that are short for a given planned output qty.

    Used by create_on_shortage_strategy (WARN/BLOCK) and complete_production
    (422 actionable list).
    """
    recipe = await recipe_service.get_recipe(db, organization_id, recipe_id)
    if recipe is None:
        raise EntityNotFoundError('maker_recipe', f'Recipe {recipe_id} not found')

    flat = await bom_service.explode_by_recipe_with_uom(
        db, organization_id, recipe_id, planned_qty
    )

    if not flat:
        return []

    needs, line_uom_ids, legacy_units = _aggregate_needs(flat)
    stocks = await _get_available_stock_batch(
        db, organization_id, list(needs), location_id=location_id
    )
    return await _shortages_from_needs(
        db,
        organization_id,
        needs=needs,
        line_uom_ids=line_uom_ids,
        legacy_units=legacy_units,
        stocks=stocks,
    )


def _aggregate_needs(
    flat: list[tuple[UUID, Decimal, str, UUID | None]],
) -> tuple[dict[UUID, Decimal], dict[UUID, UUID | None], dict[UUID, str | None]]:
    """Aggregate exploded leaves into per-template requirements.

    Kept from :func:`compute_shortage_list` when the listing's batched
    count needed the same aggregation: one explosion per recipe, scaled
    per order, answering with the same needs maps the per-order path
    builds.
    """
    needs: dict[UUID, Decimal] = {}
    line_uom_ids: dict[UUID, UUID | None] = {}
    legacy_units: dict[UUID, str | None] = {}
    for child_id, child_qty, unit, line_uom_id in flat:
        needs[child_id] = needs.get(child_id, Decimal('0')) + child_qty
        if child_id not in line_uom_ids or line_uom_ids[child_id] is None:
            line_uom_ids[child_id] = line_uom_id
        legacy_units.setdefault(child_id, unit or None)
    return needs, line_uom_ids, legacy_units


async def _shortages_from_needs(
    db: AsyncSession,
    organization_id: UUID,
    *,
    needs: dict[UUID, Decimal],
    line_uom_ids: dict[UUID, UUID | None],
    legacy_units: dict[UUID, str | None],
    stocks: dict[UUID, Decimal],
    templates: dict[UUID, ProductTemplateDTO] | None = None,
    uom_cache: dict[UUID, UomDTO | None] | None = None,
) -> list[ShortageItem]:
    """The shortage verdict for aggregated needs against a stock reading.

    The one implementation of "what counts as short" — completion's 422
    list and the order listing's count both read it, so a draft the card
    calls blocked is a draft completion refuses. Callers that process many
    orders share the template map and the unit cache across the batch.
    """
    if templates is None:
        templates = await core_api.product_templates.get_many_async(
            db, organization_id, list(needs)
        )
    if uom_cache is None:
        uom_cache = {}

    async def _get_uom(uom_id: UUID | None) -> UomDTO | None:
        if uom_id is None:
            return None
        if uom_id not in uom_cache:
            uom_cache[uom_id] = await core_api.uoms.get_async(
                db, uom_id, organization_id
            )
        return uom_cache[uom_id]

    shortages: list[ShortageItem] = []
    for child_id, needed in needs.items():
        raw_stock = stocks.get(child_id, Decimal('0'))

        recipe_uom = await _get_uom(line_uom_ids.get(child_id))
        template = templates.get(child_id)
        stock_uom = await _get_uom(template.uom_id if template else None)

        converted = raw_stock
        convertible = True
        if recipe_uom is not None and stock_uom is not None:
            if recipe_uom.id != stock_uom.id:
                converted, convertible = core_api.uoms.convert_quantity(
                    raw_stock, stock_uom, recipe_uom
                )

        # An ingredient nobody can measure against the requirement still
        # stops the order — but as "unknown", not as an invented quantity.
        shortage = (needed - converted) if convertible else None
        if shortage is None or shortage > 0:
            shortages.append(
                ShortageItem(
                    child_template_id=child_id,
                    child_template_name=template.name if template else None,
                    needed=needed,
                    available=converted,
                    shortage=shortage,
                    uom_symbol=_line_unit_symbol(
                        recipe_uom,
                        stock_uom.symbol if stock_uom else None,
                        legacy_units.get(child_id),
                    ),
                    convertible=convertible,
                    available_uom_symbol=stock_uom.symbol
                    if not convertible and stock_uom
                    else None,
                )
            )

    return shortages


async def shortage_signals_for_orders(
    db: AsyncSession,
    organization_id: UUID,
    orders: list[ProductionOrder],
) -> dict[UUID, list[ShortageItem]]:
    """Each draft order's shortage list, completion's way, for a page.

    Completion refuses a run on :func:`compute_shortage_list` at the
    order's own output location, and an ingredient nobody can measure
    counts as blocked too. A listing that recomputed that per order paid
    the whole explosion and stock read per row — a page of drafts meant
    hundreds of queries. This batches it without changing the verdict:
    one recipe round for the whole page (``explode_by_recipes_with_uom``),
    one stock read per distinct location scope, one template read and one
    unit cache for the page, and the same ``_shortages_from_needs``
    deciding what a shortage is. The listing reads the count of each list,
    the order page reads the list itself — both the refusal's own answer.

    Orders past the draft get no entry — their consumption already
    happened, and a forecast about it is noise. A draft without a recipe
    has nothing to explode and gets no entry either; its ``shortage_count``
    reads as null, not as a clean zero.
    """
    drafts = [o for o in orders if o.status == 'DRAFT' and o.recipe_id is not None]
    if not drafts:
        return {}

    recipe_rows = await db.execute(
        select(MakerRecipe.id, MakerRecipe.batch_yield_qty).where(
            MakerRecipe.id.in_({o.recipe_id for o in drafts}),
            MakerRecipe.organization_id == organization_id,
        )
    )
    yields: dict[UUID, Decimal] = {row[0]: row[1] for row in recipe_rows.all()}

    # The scope rule completion applies, decided through the same function
    # the single-order check reads — the setting is organisation-level, the
    # context location is each order's own.
    settings = await recipe_service.get_settings(db, organization_id, for_update=False)

    def _scope(order: ProductionOrder) -> UUID | None:
        return _resolve_scope(
            settings.availability_check_scope, None, order.output_storage_location_id
        )

    # One recipe round for the page, each order exploded at its own plan:
    # a need scaled from a one-batch explosion carries the rounded per-batch
    # figure of any sub-assembly the yield does not divide, and a run with
    # exactly enough stock would read as a trillionth short. A recipe whose
    # yield cannot scale a plan has no explosion to give (as before).
    plans = {
        (o.recipe_id, o.planned_qty)
        for o in drafts
        if o.recipe_id is not None and (yields.get(o.recipe_id) or Decimal('0')) > 0
    }
    needs_by_plan: dict[
        tuple[UUID, Decimal],
        tuple[dict[UUID, Decimal], dict[UUID, UUID | None], dict[UUID, str | None]],
    ] = {}
    for plan, flat in (
        await bom_service.explode_by_recipes_with_uom(db, organization_id, plans)
    ).items():
        if flat:
            needs_by_plan[plan] = _aggregate_needs(flat)

    stocks_by_scope: dict[UUID | None, dict[UUID, Decimal]] = {}
    children_by_scope: dict[UUID | None, set[UUID]] = {}
    for o in drafts:
        assert o.recipe_id is not None  # drafts is filtered on recipe_id
        maps = needs_by_plan.get((o.recipe_id, o.planned_qty))
        if maps is None:
            continue
        children_by_scope.setdefault(_scope(o), set()).update(maps[0])
    for scope, children in children_by_scope.items():
        stocks_by_scope[scope] = await _get_available_stock_batch(
            db, organization_id, sorted(children), location_id=scope
        )

    templates: dict[UUID, ProductTemplateDTO] | None = None
    uom_cache: dict[UUID, UomDTO | None] = {}
    all_children = sorted({c for m in needs_by_plan.values() for c in m[0]})
    if all_children:
        templates = await core_api.product_templates.get_many_async(
            db, organization_id, all_children
        )
    signals: dict[UUID, list[ShortageItem]] = {}
    for o in drafts:
        assert o.recipe_id is not None  # drafts is filtered on recipe_id
        maps = needs_by_plan.get((o.recipe_id, o.planned_qty))
        if maps is None:
            continue
        needs, line_uom_ids, legacy_units = maps
        signals[o.id] = await _shortages_from_needs(
            db,
            organization_id,
            needs=needs,
            line_uom_ids=line_uom_ids,
            legacy_units=legacy_units,
            stocks=stocks_by_scope[_scope(o)],
            templates=templates,
            uom_cache=uom_cache,
        )
    return signals


def _resolve_scope(
    scope: str,
    requested_location_id: UUID | None,
    context_location_id: UUID | None,
) -> UUID | None:
    """The check-scope rule, decided on an already-read setting.

    - an explicit ``requested_location_id`` (query param) always wins;
    - ``PER_LOCATION`` narrows the check to the context location (e.g. the
      production order's output location); without a context location the
      check falls back to GLOBAL;
    - ``GLOBAL`` (default) always sums stock across locations.

    Every reader of the availability scope goes through this one function —
    the single-order check and the page batch decide alike, so PER_LOCATION
    cannot come to mean two things.
    """
    if requested_location_id is not None:
        return requested_location_id
    if scope == 'PER_LOCATION':
        return context_location_id
    return None


async def resolve_check_location(
    db: AsyncSession,
    organization_id: UUID,
    *,
    requested_location_id: UUID | None = None,
    context_location_id: UUID | None = None,
) -> UUID | None:
    """Resolve the effective location scope for an availability check.

    Reads the organisation's ``availability_check_scope`` without
    the write lock and hands the decision to ``_resolve_scope`` — the same
    rule the page batch applies.
    """
    settings = await recipe_service.get_settings(db, organization_id, for_update=False)
    return _resolve_scope(
        settings.availability_check_scope, requested_location_id, context_location_id
    )
