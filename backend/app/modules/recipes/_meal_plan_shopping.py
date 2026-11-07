"""Async shopping list generation for meal plans (split from _meal_plan)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.contracts import (
    ProductTemplateDTO,
    ShoppingListItemCreateDTO,
    UomDTO,
)
from app.core.contracts.events import RecipeMealPlanGeneratedPayload
from app.core.datetimes import format_date_for
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api
from app.core.utils import isoformat_or_none
from app.i18n import Language
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

from ._availability import build_stock_context, resolve_template
from ._constants import localized
from ._helpers import _round_shopping_qty
from ._meal_plan_async_schema import _require_plan_async
from ._meal_plan_helpers import _get_effective_servings, listed_meals_of
from ._name_matching import match_key
from ._shopping_overlap import lines_listed_elsewhere
from ._shopping_rule import load_exclusions, quantity_to_buy
from ._uom_helpers import convert_qty_for_template
from .events import RecipeEvent
from .models import (
    Recipe,
    RecipeIngredient,
)
from .schemas import (
    ShoppingListGenerationResult,
    _GeneratedItem,
)

# Server-generated list name and item notes per request language.
# Must not be hardcoded English — see protocol_service pattern.
_NOTES_LABELS: dict[str, str] = {
    'en': 'Needed by: {date}',
    'pl': 'Potrzebne do: {date}',
    'de': 'Benötigt bis: {date}',
    'fr': 'Nécessaire avant le : {date}',
    'es': 'Necesario para: {date}',
}

_LIST_NAME_LABELS: dict[str, str] = {
    'en': 'Shopping list \u2014 {plan}',
    'pl': 'Lista zakupów \u2014 {plan}',
    'de': 'Einkaufsliste \u2014 {plan}',
    'fr': 'Liste de courses \u2014 {plan}',
    'es': 'Lista de la compra \u2014 {plan}',
}


# Emitted when the goods were found but the recipe's measure and the
# stock's cannot be put on one scale. Buying the full amount and saying so
# beats a deficit computed across incompatible units. Kept as the composed
# fallback in `notes`; the structured parts in `note_data` let the interface
# re-render the sentence in its own language.
_CHECK_STOCK_LABELS: dict[str, str] = {
    'en': 'Check stock: {available} in stock, recipe needs {required}',
    'pl': 'Sprawdź stan: {available} na stanie, przepis wymaga {required}',
    'de': 'Bestand prüfen: {available} vorhanden, Rezept braucht {required}',
    'fr': 'Vérifier le stock : {available} en stock, la recette demande {required}',
    'es': 'Comprobar existencias: {available} en stock, la receta necesita {required}',
}

# Emitted when the line was deducted against a product carrying a different
# name, so the user can see why something was subtracted.
_APPROX_MATCH_LABELS: dict[str, str] = {
    'en': 'Matched by name to "{product}"',
    'pl': 'Dopasowano po nazwie do „{product}”',
    'de': 'Über den Namen "{product}" zugeordnet',
    'fr': 'Rapproché par le nom de « {product} »',
    'es': 'Emparejado por nombre con «{product}»',
}


def _written_date(value: date, lang: str) -> str:
    """The date as that language writes it.

    The note is prose a person reads, so the date follows the same convention
    as the rest of that language's interface — the table lives in
    ``app.core.datetimes``, beside the canonical format it is the alternative
    to, so the two ways of writing a date are read from one place.
    """
    return format_date_for(lang, value)


def _measured(quantity: Decimal, uom: UomDTO | None) -> str:
    """Render a quantity for a note a person reads: "7 pcs", not "7.000 pcs"."""
    trimmed = f'{quantity.normalize():f}'
    return f'{trimmed} {uom.symbol}' if uom else trimmed


@dataclass(frozen=True)
class _StockVerdict:
    """What the shelf says about one aggregated shopping line."""

    covered: bool
    deficit: Decimal
    comparable: bool = True
    available_text: str | None = None
    # Raw shelf reading in the product's own unit, for the structured note:
    # the interface composes the check-stock sentence itself and translates
    # the unit symbol through its own catalog.
    available_qty: int | None = None
    available_uom_id: UUID | None = None


def _line_notes(
    lang: str,
    *,
    needed_by: date | None,
    verdict: _StockVerdict,
    approximate_product: str | None,
    required_text: str,
) -> str | None:
    """Assemble the note a shopping line carries, honestly and in the user's language."""
    parts: list[str] = []
    if needed_by:
        parts.append(
            localized(_NOTES_LABELS, lang, date=_written_date(needed_by, lang))
        )
    if not verdict.comparable and verdict.available_text:
        parts.append(
            localized(
                _CHECK_STOCK_LABELS,
                lang,
                available=verdict.available_text,
                required=required_text,
            )
        )
    if approximate_product:
        parts.append(localized(_APPROX_MATCH_LABELS, lang, product=approximate_product))
    return ' · '.join(parts) if parts else None


def _note_data(
    *,
    needed_by: date | None,
    verdict: _StockVerdict,
    required_qty: Decimal,
    required_uom_id: UUID | None,
    approximate_product: str | None,
) -> dict[str, Any] | None:
    """The note as structured parts, not a sentence.

    A server-composed sentence freezes the language of whoever happened to
    trigger the generation. The parts re-render on the client in the
    reader's language — including the unit symbols, which the interface
    already translates. Composed `notes` stays beside it as the fallback.
    """
    data: dict[str, Any] = {}
    if needed_by:
        data['needed_by'] = needed_by.isoformat()
    if not verdict.comparable and verdict.available_qty is not None:
        data['check_stock'] = {
            'available_qty': float(verdict.available_qty),
            'available_uom_id': (
                str(verdict.available_uom_id) if verdict.available_uom_id else None
            ),
            'required_qty': float(required_qty),
            'required_uom_id': str(required_uom_id) if required_uom_id else None,
        }
    if approximate_product:
        data['matched_by_name'] = approximate_product
    return data or None


async def _measure_key(
    db: AsyncSession,
    uom: UomDTO | None,
    canonical: dict[UUID | None, tuple[Decimal, str] | None],
) -> str:
    """What *uom* measures — the name two lines must share before their
    numbers may be added.

    The category's reference symbol when the unit converts to one, so ``kg``
    and ``g`` both answer ``g`` and buy the same goods once. A unit with no
    canonical measure — a piece, a pack, a bottle — answers only for itself:
    a pack is not a share of a piece, and adding the two produced a number in
    no unit at all.

    The unit table is asked once per unit; the answer is a property of the
    unit, not of the line being aggregated.
    """
    if uom is None:
        return ''
    if uom.id not in canonical:
        canonical[uom.id] = await core_api.uoms.to_canonical_measure_async(
            db, Decimal('1'), uom
        )
    measure = canonical[uom.id]
    return measure[1] if measure else f'uom:{uom.id}'


def _restate(
    qty: Decimal, source: UomDTO | None, target: UomDTO | None
) -> tuple[Decimal, bool]:
    """*qty*, stated in *source*, expressed in *target* — or a refusal.

    Two bare numbers with no unit on either side are the one case that adds
    up as it stands; every other pair goes through the catalogue's own
    conversion, and a refusal is answered with a row of its own rather than
    with the raw number.
    """
    if source is None and target is None:
        return qty, True
    return core_api.uoms.convert_quantity(qty, source, target)


async def _stock_verdict(
    db: AsyncSession,
    org_id: UUID,
    template: ProductTemplateDTO | None,
    required_qty: Decimal,
    ingredient_uom: UomDTO | None,
    uoms_by_id: dict[UUID, UomDTO],
) -> _StockVerdict:
    """Weigh what is on the shelf against what the plan needs.

    The deduction runs through the same unit bridge availability uses. It
    used to compare a StockQuant total, in the product's own unit, against
    a quantity in the recipe's — harmless only while the branch never ran
    for an ingredient without a template link, and about to start producing
    deficits like "363.6 g short" derived from 36.4 cans.
    """
    if template is None:
        return _StockVerdict(covered=False, deficit=required_qty)

    quants = await core_api.stock.list_quants_async(
        db, org_id, product_template_id=template.id
    )
    # What is free, not what is on the shelf. Goods another document has
    # reserved are spoken for, and counting them as cover made the list say
    # "nothing to buy" over stock somebody else was already going to take --
    # exactly when the warehouse is busiest, which is when buying too little
    # costs the most.
    on_hand = sum((q.available_quantity for q in quants), Decimal('0'))
    stock_uom = uoms_by_id.get(template.uom_id) if template.uom_id else None
    available = convert_qty_for_template(
        on_hand, stock_uom, ingredient_uom, template, uoms_by_id
    )

    if available is None:
        return _StockVerdict(
            covered=False,
            deficit=required_qty,
            comparable=False,
            available_text=_measured(on_hand, stock_uom),
            available_qty=int(on_hand),
            available_uom_id=stock_uom.id if stock_uom else None,
        )
    if available >= required_qty:
        return _StockVerdict(covered=True, deficit=Decimal('0'))
    return _StockVerdict(covered=False, deficit=required_qty - available)


async def generate_shopping_list_async(  # noqa: C901, PLR0915 - existing complexity/size
    db: AsyncSession,
    plan_id: UUID,
    org_id: UUID,
    user_id: UUID,
    lang: Language = 'en',
) -> ShoppingListGenerationResult:
    plan = await _require_plan_async(db, plan_id, org_id)

    if not plan.entries:
        raise ServiceRejectionError('meal_plan_empty')

    # A plan that already has a list is not done shopping: entries may have
    # been added since. The run goes on — the existing list is refreshed with
    # the lines it does not carry yet, and the answer describes what the plan
    # needs now. It used to return the list with a zero count and no items,
    # so nothing added after the first generation ever reached it.
    existing_list = None
    if plan.shopping_list_id is not None:
        existing_list = await shopping_lists_api.get_shopping_list_async(
            db, plan.shopping_list_id, org_id
        )

    recipe_ids = {e.recipe_id for e in plan.entries}
    recipes_map: dict[UUID, Recipe] = {}
    if recipe_ids:
        rows = (
            (
                await db.scalars(
                    select(Recipe)
                    .options(
                        joinedload(Recipe.ingredients).joinedload(RecipeIngredient.uom)
                    )
                    .where(Recipe.id.in_(list(recipe_ids)))
                )
            )
            .unique()
            .all()
        )
        for r in rows:
            recipes_map[r.id] = r

    stock = await build_stock_context(
        db,
        [
            ing
            for recipe in recipes_map.values()
            for ing in recipe.ingredients
            if not ing.is_optional
        ],
        org_id,
    )
    uoms_by_id = {
        uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }

    aggregated: dict[tuple[str, str], dict[str, Any]] = {}
    #: One unit of each unit, in its category's reference measure — asked
    #: once per unit, not once per line.
    canonical: dict[UUID | None, tuple[Decimal, str] | None] = {}

    for entry in plan.entries:
        recipe = recipes_map.get(entry.recipe_id)
        if recipe is None:
            continue
        effective_servings = _get_effective_servings(entry, plan, recipe)

        from ._scaling import resolve_multiplier

        multiplier = resolve_multiplier(recipe.servings, effective_servings, None)

        for ing in recipe.ingredients:
            # Skip optional ingredients — they shouldn't appear on the shopping list
            if ing.is_optional:
                continue

            ing_uom = uoms_by_id.get(ing.uom_id) if ing.uom_id else None
            # What the list asks for is a requirement, so it takes the next
            # step of its own unit: a third of an egg is an egg to buy, and
            # rounding it to the nearest step would ask for none.
            scaled_qty = core_api.uoms.round_up(
                Decimal(str(ing.quantity)) * multiplier, ing_uom
            )
            # Aggregate on the product the ingredient resolves to, so two
            # recipes wording the same goods differently buy it once — but
            # only within one measure. "500 g" and "2 pcs" of a product are
            # two lines on the list; added together they were a number in no
            # unit at all, which is what a shopper cannot act on.
            resolved = resolve_template(ing, stock)
            product_key = str(resolved.id) if resolved else match_key(ing.name)
            agg_key = (product_key, await _measure_key(db, ing_uom, canonical))

            existing = aggregated.get(agg_key)
            if existing is not None:
                target_uom = (
                    uoms_by_id.get(existing['uom_id']) if existing['uom_id'] else None
                )
                converted, mergeable = _restate(scaled_qty, ing_uom, target_uom)
                if mergeable:
                    existing['quantity'] = core_api.uoms.round_up(
                        existing['quantity'] + converted, target_uom
                    )
                    if entry.date < existing['needed_by']:
                        existing['needed_by'] = entry.date
                    continue
                # Sharing a measure means the conversion already succeeded
                # once, so today's catalogue does not produce this pair. The
                # net stays because falling through would overwrite the row
                # already under this key — a line would leave the list
                # silently instead of standing on its own.
                agg_key = (product_key, f'unconvertible:{ing.uom_id}')
                if agg_key in aggregated:
                    aggregated[agg_key]['quantity'] += scaled_qty
                    continue

            aggregated[agg_key] = {
                'name': ing.name,
                'quantity': scaled_qty,
                'uom_id': ing.uom_id,
                'template_id': ing.template_id,
                'resolved_template': resolved,
                'approximate': resolved is not None and ing.template_id is None,
                'needed_by': entry.date,
            }

    exclusions = await load_exclusions(db, org_id)
    exclusion_keys = [
        key
        for key, value in aggregated.items()
        if exclusions.excludes(value['name'], value['template_id'])
    ]
    for exclusion_key in exclusion_keys:
        del aggregated[exclusion_key]

    to_buy_items: list[ShoppingListItemCreateDTO] = []
    to_buy_display: list[_GeneratedItem] = []
    available_count = 0
    total = len(aggregated)

    for agg_key, agg in aggregated.items():
        product: ProductTemplateDTO | None = agg['resolved_template']
        required_qty = agg['quantity']
        ingredient_uom = uoms_by_id.get(agg['uom_id']) if agg['uom_id'] else None

        verdict = await _stock_verdict(
            db, org_id, product, required_qty, ingredient_uom, uoms_by_id
        )
        if verdict.covered:
            available_count += 1
            continue

        # The shared arithmetic, the same the recipe screen runs: wanted less
        # what the shelf covers, or the whole requirement when the two
        # measures cannot be compared.
        qty_target = quantity_to_buy(
            required_qty,
            required_qty - verdict.deficit,
            comparable=verdict.comparable,
        )
        if qty_target is None:
            continue
        qty = _round_shopping_qty(qty_target, ingredient_uom)
        if qty <= 0:
            # A deficit that rounds to the unit's zero says "buy nothing" —
            # there is nothing to buy. Skipping it keeps one unmeasurable
            # ingredient from failing the whole plan's list.
            continue
        needed_by = agg['needed_by']
        notes = _line_notes(
            lang,
            needed_by=needed_by,
            verdict=verdict,
            approximate_product=(
                product.name if product is not None and agg['approximate'] else None
            ),
            required_text=_measured(required_qty, ingredient_uom),
        )
        to_buy_items.append(
            ShoppingListItemCreateDTO(
                name=agg['name'],
                quantity=qty,
                uom_id=agg['uom_id'],
                source='meal_plan',
                template_id=product.id if product else None,
                notes=notes,
                note_data=_note_data(
                    needed_by=needed_by,
                    verdict=verdict,
                    required_qty=required_qty,
                    required_uom_id=agg['uom_id'],
                    approximate_product=(
                        product.name
                        if product is not None and agg['approximate']
                        else None
                    ),
                ),
            )
        )
        to_buy_display.append(
            _GeneratedItem(
                key=':'.join(agg_key),
                name=agg['name'],
                quantity=qty,
                uom_id=agg['uom_id'],
                uom_symbol=ingredient_uom.symbol if ingredient_uom else None,
                needed_by=isoformat_or_none(needed_by),
                quantities_comparable=verdict.comparable,
                matched_approximately=bool(agg['approximate']),
            )
        )

    plan_name = plan.name or f'Meal Plan {plan.start_date} \u2013 {plan.end_date}'
    if existing_list is not None:
        sl = existing_list
        already_listed = await shopping_lists_api.get_list_items_async(
            db, sl.id, org_id
        )
        existing_keys = {
            (item.name.strip().lower(), item.uom_id) for item in already_listed
        }
        new_items = [
            item
            for item in to_buy_items
            if (item.name.strip().lower(), item.uom_id) not in existing_keys
        ]
        if new_items:
            await shopping_lists_api.add_items_async(db, sl.id, new_items, org_id)
        written = new_items
    else:
        sl = await shopping_lists_api.create_shopping_list_async(
            db,
            org_id,
            user_id,
            name=localized(_LIST_NAME_LABELS, lang, plan=plan_name),
            lang=lang,
        )
        if to_buy_items:
            await shopping_lists_api.add_items_async(db, sl.id, to_buy_items, org_id)
        written = to_buy_items

    plan.shopping_list_id = sl.id
    # What the list was made from, for the plan screen to compare against.
    plan.listed_meals = listed_meals_of(plan)
    await db.flush()
    await core_api.events.emit_transactional_async(
        db,
        RecipeEvent.MEAL_PLAN_GENERATED,
        RecipeMealPlanGeneratedPayload(
            organization_id=str(org_id),
            plan_id=str(plan_id),
            shopping_list_id=str(sl.id),
            to_buy_count=len(to_buy_items),
        ),
    )
    await db.flush()

    return ShoppingListGenerationResult(
        shopping_list_id=sl.id,
        total_ingredients=total,
        available_count=available_count,
        to_buy_count=len(to_buy_items),
        items=to_buy_display,
        on_other_lists=await lines_listed_elsewhere(db, org_id, written, list_id=sl.id),
    )
