"""Recipe ingredient availability computation.

Status semantics:
  - 'available'        : the ingredient's own template, and enough of it
  - 'available_approx' : resolved from the ingredient's name, and enough of it
  - 'insufficient'     : on the shelf, but less than the recipe asks for
  - 'missing'          : nothing on the shelf fit to cook with (stock past its
                         date is shown, flagged, and counts for nothing)
  - 'unknown'          : the ingredient names nothing that can be looked up

'insufficient' and 'missing' were one status, so 492 ml of the 500 ml a
recipe wants read exactly like no milk at all — and the reader, told the milk
was missing, went shopping for what was already in the fridge.

Everything is resolved on read. A recipe is saved once while the catalogue
changes daily, so freezing the resolution at save time would hide every
product added afterwards until somebody re-saved the recipe by hand.

The reads are batched into a :class:`StockContext` — five queries, whether
the caller asks about one recipe or two hundred. There used to be two
nearly identical code paths, one with a cache and one without; a context
that a lone recipe also builds removes that fork.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.contracts import ItemDTO, ProductTemplateDTO, UomDTO
from app.core.public_api import core_api

from ._crud import list_recipes
from ._helpers import _item_to_schema
from ._ingredient_matching import (
    IngredientMatch,
    match_templates,
    matching_key,
    narrowing_fragment,
)
from ._picking_fefo import fefo_days_left, fefo_order, is_past
from ._uom_helpers import convert_qty_for_template
from .models import Recipe, RecipeIngredient
from .schemas import IngredientAvailability, RecipeAvailability, RecipeList

if TYPE_CHECKING:
    from ._shopping_rule import ShoppingExclusions


@dataclass(frozen=True)
class StockContext:
    """Everything the availability rules need, loaded once per request."""

    items_by_template: dict[UUID, list[ItemDTO]]
    candidates_by_key: dict[str, list[IngredientMatch]]
    templates_by_id: dict[UUID, ProductTemplateDTO]
    uoms_by_id: dict[UUID, UomDTO]
    #: The organization's day, which decides what is past its date.
    today: date


async def build_stock_context(
    db: Any,
    ingredients: list[RecipeIngredient],
    organization_id: UUID,
) -> StockContext:
    """Resolve every ingredient to catalogue candidates and load their stock.

    Five queries regardless of how many ingredients arrive: candidates,
    units, the organization's day, items, templates. The templates come
    along for their pack size — without it a requirement in grams cannot be
    weighed against stock counted in pieces. The units come along even when
    the catalogue matched nothing, because the requirement is stated in
    their step either way. The day decides what is past its date.
    """
    keys = {key for ing in ingredients if (key := matching_key(ing))}
    candidates_by_key = await _match_keys_to_catalog(db, keys, organization_id)

    template_ids = {ing.template_id for ing in ingredients if ing.template_id}
    for matches in candidates_by_key.values():
        template_ids.update(match.template_id for match in matches)

    # Read before the early return: with an empty unit map the step fell back
    # to the quantity columns' scale, so a recipe for three cooked for one
    # asked for 0.334 of an egg — on an empty pantry, which is exactly when
    # someone reads that number.
    #
    # The map answers for the caller's rows and the system's only, and that
    # scope is the decision, measured on a live stack: an ingredient naming
    # a unit of ANOTHER organization (an id the pickers never offer) drops
    # out of the map, and its line rounds on the column scale — 1.333 stayed
    # 1.333 where the unit's own 0.5 step would have said 1.5. Reading that
    # row anyway would answer a cross-tenant reference with a unit this
    # organization cannot see, name, or convert, so the missing unit is the
    # right answer here; the write side is where a reference like that
    # belongs — refused, not honoured.
    uoms = await core_api.uoms.list_for_org_async(db, organization_id)
    uoms_by_id = {uom.id: uom for uom in uoms}
    today = await core_api.organizations.today_async(db, organization_id)

    if not template_ids:
        return StockContext({}, candidates_by_key, {}, uoms_by_id, today)

    ids = list(template_ids)
    items_by_template = await core_api.items.list_with_template_async(
        db, organization_id, ids
    )
    templates_by_id = await core_api.product_templates.get_many_async(
        db, organization_id, ids
    )
    return StockContext(
        items_by_template=items_by_template,
        candidates_by_key=candidates_by_key,
        templates_by_id=templates_by_id,
        uoms_by_id=uoms_by_id,
        today=today,
    )


async def _match_keys_to_catalog(
    db: Any, keys: set[str], organization_id: UUID
) -> dict[str, list[IngredientMatch]]:
    """Rank the catalogue against each lookup key, best candidate first."""
    fragments = {f for key in keys if (f := narrowing_fragment(key))}
    if not fragments:
        return {}
    pools = await core_api.product_templates.search_fuzzy_many_async(
        db, organization_id, sorted(fragments)
    )
    resolved: dict[str, list[IngredientMatch]] = {}
    for key in keys:
        fragment = narrowing_fragment(key)
        pool = pools.get(fragment, []) if fragment else []
        resolved[key] = match_templates(key, pool)
    return resolved


async def get_recipe_availability(
    db: Any,
    recipe: Recipe,
    organization_id: UUID,
    servings_requested: int | Decimal,
    context: StockContext | None = None,
    scale: Decimal | None = None,
    exclusions: ShoppingExclusions | None = None,
) -> RecipeAvailability:
    """One recipe's availability, optionally flagged with the buy rule.

    The shopping door passes the organization's exclusions so each line
    carries whether the list rule would leave it out; callers that never
    ask "what must be bought" — picking, the planner — leave it ``None``
    and pay nothing for the question.
    """
    if context is None:
        context = await build_stock_context(
            db, list(recipe.ingredients), organization_id
        )

    from ._scaling import resolve_multiplier, rounded_servings, serving_equivalent

    multiplier = resolve_multiplier(recipe.servings, servings_requested, scale)
    exact_servings = serving_equivalent(recipe.servings, multiplier)
    ingredients_result: list[IngredientAvailability] = []

    for ingredient in recipe.ingredients:
        # The step is the ingredient's own unit's, not a hard three places:
        # a recipe scaled down asks for part of an egg, and part of an egg is
        # an egg. What the recipe originally said is a reading, not a demand,
        # so it takes the nearest step instead.
        ingredient_uom = (
            context.uoms_by_id.get(ingredient.uom_id) if ingredient.uom_id else None
        )
        # The scaled requirement before its unit's step rounds it up. Kept
        # only when the step changes it: the card names it as what the shown
        # number was rounded from, and a requirement already on its step has
        # nothing to explain — including one the multiplier's last-place
        # noise puts a hair above it, which the step's own answer reads as
        # on the step.
        unrounded_qty = Decimal(str(ingredient.quantity)) * multiplier
        required_qty = core_api.uoms.round_up(unrounded_qty, ingredient_uom)
        unrounded_reported = (
            None
            if core_api.uoms.is_on_step(unrounded_qty, ingredient_uom)
            else float(unrounded_qty)
        )
        scaled_orig_qty = None
        if ingredient.original_quantity is not None:
            scaled_orig_qty = float(
                core_api.uoms.quantize(
                    ingredient.original_quantity * multiplier, ingredient_uom
                )
            )
        ingredients_result.append(
            _check_ingredient_availability(
                ingredient=ingredient,
                required_qty=required_qty,
                context=context,
                original_quantity=scaled_orig_qty,
                unrounded_quantity=unrounded_reported,
                # The same exclusion the list rule skips a line for: by
                # product first, by name otherwise. Computed from the recipe
                # row, not the matched stock — the link on the ingredient is
                # what `collect_shopping_items` reads too.
                excluded=(
                    exclusions.excludes(ingredient.name, ingredient.template_id)
                    if exclusions is not None
                    else False
                ),
            )
        )

    optional_ids = {i.id for i in recipe.ingredients if i.is_optional}
    non_optional = [
        i for i in ingredients_result if i.ingredient_id not in optional_ids
    ]
    available_count = sum(
        1 for i in non_optional if i.status in ('available', 'available_approx')
    )
    match_pct = available_count / len(non_optional) if non_optional else 1.0

    return RecipeAvailability(
        recipe_id=recipe.id,
        recipe_name=recipe.name,
        servings_requested=rounded_servings(exact_servings),
        scale=float(multiplier),
        match_percentage=round(match_pct, 2),
        ingredients=ingredients_result,
    )


def _resolve_stock(
    ingredient: RecipeIngredient, context: StockContext
) -> tuple[list[ItemDTO], str | None, ProductTemplateDTO | None]:
    """Return the stock backing this ingredient, how it was found, and its template.

    The ingredient's own template wins when it has stock. Otherwise the
    best-ranked catalogue name that does — one template rather than the
    union of every candidate, because adding "Cukier waniliowy" onto
    "Cukier biały" would report a total nobody can cook with, and because a
    pack size only means anything for a single product.
    """
    if ingredient.template_id:
        items = context.items_by_template.get(ingredient.template_id, [])
        if items:
            return items, 'exact', context.templates_by_id.get(ingredient.template_id)

    key = matching_key(ingredient)
    for match in context.candidates_by_key.get(key, []) if key else []:
        items = context.items_by_template.get(match.template_id, [])
        if items:
            return items, 'fuzzy', context.templates_by_id.get(match.template_id)

    return [], None, None


def resolve_template(
    ingredient: RecipeIngredient, context: StockContext
) -> ProductTemplateDTO | None:
    """Return the catalogue product this ingredient stands for, stocked or not.

    Prefers a candidate that actually has stock — that is the one a
    shopping list should deduct against — and otherwise falls back to the
    best-ranked name match, so two spellings of an out-of-stock product
    still aggregate onto one line instead of buying it twice.
    """
    _, _, stocked = _resolve_stock(ingredient, context)
    if stocked is not None:
        return stocked

    key = matching_key(ingredient)
    for match in context.candidates_by_key.get(key, []) if key else []:
        candidate = context.templates_by_id.get(match.template_id)
        if candidate is not None:
            return candidate

    if ingredient.template_id:
        return context.templates_by_id.get(ingredient.template_id)
    return None


def measures_meet(
    ingredient: RecipeIngredient,
    template: ProductTemplateDTO,
    context: StockContext,
) -> bool:
    """Whether the availability comparison would weigh this line against *template*.

    Against its stock when it has any, against the unit it is counted in
    otherwise; a product that names no unit has nothing to refuse with. A
    product refused here is one the recipe line cannot be sized against —
    "Salt, 1" against bags of crisps — and borrowing its figures elsewhere
    (its macros, its pack weight) would sum what the card beside it
    declines to compare.
    """
    items = context.items_by_template.get(template.id, [])
    if items:
        total = _total_available(items, ingredient.uom, template, context.uoms_by_id)
        return total is not None
    stock_uom = context.uoms_by_id.get(template.uom_id) if template.uom_id else None
    if stock_uom is None:
        return True
    converted = convert_qty_for_template(
        Decimal('1'), stock_uom, ingredient.uom, template, context.uoms_by_id
    )
    return converted is not None


def _total_available(
    items: list[ItemDTO],
    ingredient_uom: Any,
    template: ProductTemplateDTO | None,
    uoms_by_id: dict[UUID, UomDTO],
) -> Decimal | None:
    """Sum the stock in the recipe's unit, or None when the measures don't meet."""
    total = Decimal('0')
    for item in items:
        item_uom = uoms_by_id.get(item.uom_id) if item.uom_id else None
        converted = convert_qty_for_template(
            Decimal(str(item.quantity or 0)),
            item_uom,
            ingredient_uom,
            template,
            uoms_by_id,
        )
        if converted is None:
            return None
        total += converted
    return total


def _check_ingredient_availability(
    ingredient: RecipeIngredient,
    required_qty: Decimal,
    context: StockContext,
    original_quantity: float | None = None,
    unrounded_quantity: float | None = None,
    excluded: bool = False,
) -> IngredientAvailability:
    uom_symbol = ingredient.uom.symbol if ingredient.uom else None
    base: dict[str, Any] = {
        'ingredient_id': ingredient.id,
        'name': ingredient.name,
        'display_text': ingredient.display_text,
        'required_quantity': float(required_qty),
        'required_quantity_unrounded': unrounded_quantity,
        'required_uom': uom_symbol,
        'required_uom_id': ingredient.uom_id,
        'original_quantity': original_quantity,
        'original_unit_text': ingredient.original_unit_text,
        'is_linked': ingredient.template_id is not None,
        'is_spice': ingredient.is_spice,
        'excluded': excluded,
    }

    items, match_type, template = _resolve_stock(ingredient, context)

    if not items:
        nameable = bool(ingredient.template_id) or matching_key(ingredient) is not None
        return IngredientAvailability(
            **base,
            status='missing' if nameable else 'unknown',
            match_type=None,
            best_item=None,
            alternative_items=[],
        )

    sorted_items = fefo_order(items, context.today)
    best = sorted_items[0]
    # What is past its date is on the shelf, not in the pot: it counts
    # towards nothing the recipe needs. It used to count in full, so a
    # fridge holding only spoiled chicken made the curry cookable.
    usable = [item for item in sorted_items if not is_past(item, context.today)]
    if not usable:
        return IngredientAvailability(
            **base,
            status='missing',
            match_type=match_type,
            quantities_comparable=True,
            available_quantity=0.0,
            available_uom=uom_symbol,
            best_item=_item_to_schema(best, None, today=context.today),
            alternative_items=[
                _item_to_schema(i, None, today=context.today) for i in sorted_items[1:5]
            ],
        )
    total = _total_available(usable, ingredient.uom, template, context.uoms_by_id)

    if total is None:
        # The goods are there; only the two measures refuse to meet. The
        # status names that state instead of hiding inside 'available' — the
        # counters read the status, and an ingredient that could not be
        # compared counted as one that could, so "1/1 na stanie" and "Mogę
        # ugotować" answered a question the code had just admitted it could
        # not. Still not "none left": both raw readings travel along.
        comparable = False
        status = 'incomparable'
        raw_total = sum((Decimal(str(i.quantity or 0)) for i in usable), Decimal('0'))
        available_quantity = float(raw_total)
        available_uom = best.uom_symbol
    else:
        comparable = True
        available_quantity = float(total)
        available_uom = uom_symbol
        if total < required_qty:
            status = 'insufficient'
        elif match_type == 'exact':
            status = 'available'
        else:
            status = 'available_approx'

    return IngredientAvailability(
        **base,
        status=status,
        match_type=match_type,
        quantities_comparable=comparable,
        available_quantity=available_quantity,
        available_uom=available_uom,
        best_item=_item_to_schema(
            best, fefo_days_left(sorted_items, context.today), today=context.today
        ),
        alternative_items=[
            _item_to_schema(i, None, today=context.today) for i in sorted_items[1:5]
        ],
    )


async def _find_available_items(
    db: Any,
    ingredient: RecipeIngredient,
    organization_id: UUID,
) -> list[ItemDTO]:
    """Return the stock fit to cook with for one ingredient, FEFO-ordered.

    Stock past its date is left out: it is not what a picker should be sent
    to fetch, and a checklist that recommended it was a checklist that
    recommended the one pack to throw away.
    """
    context = await build_stock_context(db, [ingredient], organization_id)
    items, _, _ = _resolve_stock(ingredient, context)
    return fefo_order(
        (item for item in items if not is_past(item, context.today)), context.today
    )


def stock_coverage(recipe: Recipe, avail: RecipeAvailability) -> tuple[int, int]:
    """How many of the recipe's required ingredients are on the shelf, of how many.

    Optional ingredients count towards neither number: a recipe is not short
    because the garnish is missing.

    The one place this pair is counted. Every surface that asks "how much of
    this can I cook" — the card, the planner's suggestions — writes the same
    two numbers, so none of them can quietly answer with a different total.
    """
    optional_ids = {i.id for i in recipe.ingredients if i.is_optional}
    required = [i for i in avail.ingredients if i.ingredient_id not in optional_ids]
    available = sum(
        1 for i in required if i.status in ('available', 'available_approx')
    )
    return available, len(required)


def _availability_summary(recipe: Recipe, avail: RecipeAvailability) -> dict[str, Any]:
    """One recipe as the list sees it, with the availability numbers attached."""
    optional_ids = {i.id for i in recipe.ingredients if i.is_optional}
    required = [i for i in avail.ingredients if i.ingredient_id not in optional_ids]
    available, total = stock_coverage(recipe, avail)
    recipe_data = RecipeList.model_validate(recipe).model_dump()
    recipe_data['ingredients_total'] = total
    recipe_data['ingredients_available'] = available
    # The third answer the card owes the reader: lines whose measure could
    # not be put on one scale with the shelf's. Neither "have" nor "missing"
    # — counted out of both, and named.
    recipe_data['ingredients_incomparable'] = sum(
        1 for i in required if i.status == 'incomparable'
    )
    # Short counts as missing here: the card names what stands between the
    # reader and cooking this, and half a bottle of milk stands there too.
    recipe_data['missing_names'] = [
        i.name for i in required if i.status in ('missing', 'insufficient')
    ]
    recipe_data['match_percentage'] = avail.match_percentage
    return recipe_data


async def annotate_recipes_with_availability(
    db: Any,
    recipes: list[Recipe],
    organization_id: UUID,
    servings: int | None = None,
) -> list[dict[str, Any]]:
    """Attach the availability summary to a page of recipes.

    The list card used to render ``ingredients_available`` straight from the
    schema default, so every recipe read "0 of N" while the detail screen, the
    cooking session and the planner — all asking this same function — said the
    ingredient was on the shelf. One stock context serves the whole page.
    """
    if not recipes:
        return []
    context = await build_stock_context(
        db, [ing for r in recipes for ing in r.ingredients], organization_id
    )
    result = []
    for recipe in recipes:
        avail = await get_recipe_availability(
            db,
            recipe,
            organization_id,
            servings or recipe.servings,
            context=context,
        )
        result.append(_availability_summary(recipe, avail))
    return result


async def get_available_recipes(
    db: Any,
    organization_id: UUID,
    min_match: float = 1.0,
    servings: int | None = None,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Recipes whose ingredients are on the shelf, with their summary.

    The default answers the question the module exists for — what could be
    cooked right now — and that is every ingredient, not most of them. A
    caller who wants the near misses too passes a lower ``min_match`` and
    says on screen that it did.
    """
    recipes, _ = await list_recipes(db, organization_id, tags=tags, limit=200)
    annotated = await annotate_recipes_with_availability(
        db, list(recipes), organization_id, servings
    )
    result = [r for r in annotated if r['match_percentage'] >= min_match]
    result.sort(key=lambda r: r['match_percentage'], reverse=True)
    return result
