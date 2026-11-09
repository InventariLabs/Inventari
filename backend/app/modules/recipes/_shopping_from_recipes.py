"""Put what one or more recipes still need onto a shopping list.

One code path serves both callers — the single-recipe button on a recipe
screen and the multi-recipe picker on a shopping list. Both answer the same
question ("what do I still have to buy for this?"), so both run the same
stock check, the same merge and the same top-up rule for what is already
listed.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from app.core.contracts import ShoppingListItemCreateDTO, ShoppingListItemDTO, UomDTO
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.public_api import core_api
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

from ._availability import build_stock_context, resolve_template
from ._constants import localized
from ._helpers import _round_shopping_qty
from ._shopping_overlap import lines_listed_elsewhere
from ._shopping_rule import load_exclusions, quantity_to_buy
from .schemas import AddToShoppingListResponse
from .services import get_recipe, get_recipe_availability

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.i18n import Language

# Shopping-list item notes per request language. Server-generated content
# must not be hardcoded English — see protocol_service pattern. The composed
# sentence is the fallback for a reader without the structured part
# (``note_data['for_recipe']``), which the list renders in its own language.
_SHOPPING_NOTE_LABELS: dict[str, str] = {
    'en': 'For recipe: {name}',
    'pl': 'Do przepisu: {name}',
    'de': 'Für Rezept: {name}',
    'fr': 'Pour la recette : {name}',
    'es': 'Para la receta: {name}',
}

# The name of the list the recipe screen makes when the organization has
# none. It used to be the recipe's own name — and that list then became the
# destination of every other recipe's missing goods, still called after the
# first one. It is a shopping list, and is named as one.
_DEFAULT_LIST_NAME_LABELS: dict[str, str] = {
    'en': 'Shopping list',
    'pl': 'Lista zakupów',
    'de': 'Einkaufsliste',
    'fr': 'Liste de courses',
    'es': 'Lista de la compra',
}


async def collect_shopping_items(
    db: AsyncSession,
    org_id: UUID,
    recipe_ids: list[UUID],
    servings: int | Decimal | None,
    scale: Decimal | None,
    lang: Language,
) -> tuple[dict[tuple[str, UUID | None], dict[str, Any]], list[str]]:
    """Aggregate what the given recipes need, keyed by (name, unit).

    Returns the merged lines and the recipe names they came from — two
    recipes wanting flour buy flour once. Each line keeps what every recipe
    asks for (``by_recipe``, the requirement before the shelf), what the
    shelf holds of it (``available``) and the shortfall of the two
    (``quantity``), the same arithmetic the meal plan applies: the
    requirements are summed first and the shelf is subtracted once. Each
    recipe used to be netted against the whole shelf on its own and the
    shortfalls added, so 250 g of flour covered Bread's 200 g and Cake's
    300 g alike and the list asked for 50 g where 250 g were short.

    A line the shelf covers stays in the answer with a zero shortfall: a
    list already carrying other recipes' need for the goods may still be
    short of it. Lines the organization marked "Always at home" are left
    out, by product or by name, as the meal plan already did.
    """
    merged: dict[tuple[str, UUID | None], dict[str, Any]] = {}
    recipe_names: list[str] = []
    exclusions = await load_exclusions(db, org_id)
    recipes = []
    for recipe_id in recipe_ids:
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)
        recipes.append(recipe)
    # One reading of the shelf for every recipe, so the goods two recipes
    # share are found on the same product and counted once.
    stock = await build_stock_context(
        db, [ing for recipe in recipes for ing in recipe.ingredients], org_id
    )

    for recipe in recipes:
        recipe_names.append(recipe.name)
        effective_servings = servings or recipe.servings
        if scale is not None:
            # A stated multiplier wins over a serving count, and multiplied
            # out it can be fractional — the availability math carries it
            # exactly.
            effective_servings = Decimal(recipe.servings) * scale
        avail = await get_recipe_availability(
            db, recipe, org_id, effective_servings, context=stock
        )

        ingredients = {ing.id: ing for ing in recipe.ingredients}
        for ing in avail.ingredients:
            source = ingredients[ing.ingredient_id]
            if exclusions.excludes(ing.name, source.template_id):
                continue
            key = (ing.name.strip().lower(), ing.required_uom_id)
            line = merged.setdefault(
                key,
                {
                    'name': ing.name,
                    'uom_id': ing.required_uom_id,
                    'by_recipe': {},
                    'shelves': {},
                },
            )
            by_recipe = line['by_recipe']
            need = Decimal(str(ing.required_quantity))
            by_recipe[recipe.name] = by_recipe.get(recipe.name, Decimal(0)) + need
            # The shelf is the product the reading came from: the same
            # product read for a second recipe is the same goods, not more
            # of them. Goods found by the ingredient's name cover it as
            # linked ones do, the way the meal plan deducts them. A reading
            # whose measure does not meet the recipe's says nothing about
            # how much it covers, so it counts for nothing and the whole
            # requirement is bought.
            product = resolve_template(source, stock)
            if product is not None and ing.quantities_comparable:
                line['shelves'][product.id] = Decimal(str(ing.available_quantity or 0))

    for line in merged.values():
        line['available'] = sum(line.pop('shelves').values(), Decimal(0))
        line['quantity'] = _shortfall(line['by_recipe'].values(), line['available'])
    return merged, recipe_names


def _shortfall(needs: Iterable[Decimal], available: Decimal) -> Decimal:
    """What *needs* summed lack once *available* is spent on them, never below 0."""
    total = sum(needs, Decimal(0))
    return quantity_to_buy(total, available, comparable=True) or Decimal(0)


def _recipe_note(recipes: list[str], lang: Language) -> str:
    return localized(_SHOPPING_NOTE_LABELS, lang, name=', '.join(recipes))


def _recipe_note_data(needs: dict[str, Decimal]) -> dict[str, Any]:
    # ``for_recipe`` is what the list renders; ``for_recipes`` keeps the
    # names apart and ``needs`` what each recipe asked for, before the shelf,
    # so a later press knows what the line already covers.
    recipes = list(needs)
    return {
        'for_recipe': ', '.join(recipes),
        'for_recipes': recipes,
        'needs': {name: str(need) for name, need in needs.items()},
    }


def _recipes_of(line: ShoppingListItemDTO) -> list[str]:
    data = line.note_data or {}
    named = data.get('for_recipes')
    if isinstance(named, list):
        return [str(name) for name in named]
    single = data.get('for_recipe')
    return [single] if isinstance(single, str) else []


def _needs_of(line: ShoppingListItemDTO) -> dict[str, Decimal] | None:
    """What each recipe asked of *line*, or None for a line that never said.

    A line written before the needs were kept names its recipes only.
    """
    needs = (line.note_data or {}).get('needs')
    if not isinstance(needs, dict):
        return None
    recorded: dict[str, Decimal] = {}
    for name, need in needs.items():
        try:
            recorded[str(name)] = Decimal(str(need))
        except InvalidOperation:
            continue
    return recorded


async def _put_on_list(
    db: AsyncSession,
    org_id: UUID,
    list_id: UUID,
    wanted: dict[str, Any],
    uom: UomDTO | None,
    lines: list[ShoppingListItemDTO],
    lang: Language,
) -> tuple[
    Literal['new', 'raised', 'listed', 'none'], ShoppingListItemCreateDTO | None
]:
    """Decide what one *wanted* line does to the *lines* the list has for it.

    ``new``: write the returned line. ``raised``: an open recipe line was
    topped up in place, and the returned line says by how much it now asks.
    ``listed``: the list already covers it. ``none``: the shelf does.

    The list asks for what its recipes need in total, less the shelf, and
    every line it has for the goods counts towards that — bought ones and
    ones typed by hand too. A line a recipe wrote records each recipe's need
    (``needs``), so a recipe pressed again at the same need is covered and
    the press stays a no-op, while one that now needs more (more servings)
    or finds less on the shelf raises the line by the growth. A recipe the
    line was made for but not pressed this time keeps its recorded need: the
    shelf is not given to the pressed one a second time. A line is never
    lowered.

    A line written before the needs were kept names its recipes only: they
    stay covered at whatever they need, as they were, and its quantity
    stands for their need.
    """
    recipe_lines = [line for line in lines if line.source == 'recipe']
    recorded: dict[str, Decimal] = {}
    unrecorded: set[str] = set()
    unrecorded_need = Decimal(0)
    for line in recipe_lines:
        line_needs = _needs_of(line)
        if line_needs is None:
            unrecorded.update(_recipes_of(line))
            unrecorded_need += line.quantity
            continue
        for name, need in line_needs.items():
            recorded[name] = max(recorded.get(name, Decimal(0)), need)
    pressed = {
        name: need
        for name, need in wanted['by_recipe'].items()
        if name not in unrecorded
    }
    grown = {
        name: need
        for name, need in pressed.items()
        if need > recorded.get(name, Decimal(0))
    }
    target = _round_shopping_qty(
        _shortfall(
            [*{**recorded, **grown}.values(), unrecorded_need], wanted['available']
        ),
        uom,
    )
    if target <= 0:
        return 'none', None
    listed = sum((line.quantity for line in lines), Decimal(0))
    shortfall = _round_shopping_qty(target - listed, uom)
    if not pressed or shortfall <= 0:
        return 'listed', None
    # The line is for the recipes whose need grew; a shelf that emptied
    # under an unchanged need is the pressed recipes' shortfall.
    added = {
        name: max(recorded.get(name, Decimal(0)), need)
        for name, need in (grown or pressed).items()
    }
    open_line = next(
        (
            line
            for line in recipe_lines
            if not line.is_purchased and _needs_of(line) is not None
        ),
        None,
    )
    item = ShoppingListItemCreateDTO(
        name=wanted['name'],
        quantity=shortfall,
        uom_id=wanted['uom_id'],
        notes=_recipe_note(list(added), lang),
        note_data=_recipe_note_data(added),
        source='recipe',
    )
    if open_line is None:
        return 'new', item
    needs = {**(_needs_of(open_line) or {}), **added}
    quantity = open_line.quantity + shortfall
    raised = await shopping_lists_api.raise_item_quantity_async(
        db,
        list_id,
        open_line.id,
        quantity,
        org_id,
        notes=_recipe_note(list(needs), lang),
        note_data={**(open_line.note_data or {}), **_recipe_note_data(needs)},
    )
    if not raised:
        return 'listed', None
    return 'raised', item.model_copy(update={'quantity': quantity})


async def add_recipes_to_shopping_list(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    recipe_ids: list[UUID],
    *,
    servings: int | Decimal | None,
    scale: Decimal | None = None,
    shopping_list_id: UUID | None,
    lang: Language,
    list_name: str | None = None,
) -> AddToShoppingListResponse:
    """Add the recipes' outstanding ingredients to a list, creating one if needed."""
    merged, _recipe_names = await collect_shopping_items(
        db, org_id, recipe_ids, servings, scale, lang
    )

    if not shopping_list_id and not any(
        line['quantity'] > 0 for line in merged.values()
    ):
        raise ServiceRejectionError('no_missing_ingredients')

    existing_items: list[ShoppingListItemDTO] = []
    if shopping_list_id:
        shopping_list = await shopping_lists_api.get_shopping_list_async(
            db, shopping_list_id, org_id
        )
        if shopping_list is None:
            raise NotFoundException('shopping_list')
        list_id = shopping_list.id
        existing_items = await shopping_lists_api.get_list_items_async(
            db, list_id, org_id
        )
    else:
        shopping_list = await shopping_lists_api.create_shopping_list_async(
            db,
            org_id=org_id,
            created_by=user_id,
            name=list_name or localized(_DEFAULT_LIST_NAME_LABELS, lang),
            lang=lang,
        )
        list_id = shopping_list.id

    # The rounding reads the unit's own step, so the unit has to be
    # resolved before a line is rounded — once for the whole page, the way
    # the meal-plan path builds its map: a loop of get_async made the query
    # count grow with the number of merged lines (a recipe may name a
    # hundred ingredients).
    uoms_by_id = {
        uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    lines_by_key: dict[tuple[str, UUID | None], list[ShoppingListItemDTO]] = {}
    for existing in existing_items:
        lines_by_key.setdefault(
            (existing.name.strip().lower(), existing.uom_id), []
        ).append(existing)
    new_items: list[ShoppingListItemCreateDTO] = []
    raised_items: list[ShoppingListItemCreateDTO] = []
    # What is missing but already on the list: a second press added
    # nothing and said "Added 0 items", which reads as "nothing was
    # missing" or "it failed" — the count lets the screen say which.
    already_listed = 0
    for key, wanted in merged.items():
        uom = uoms_by_id.get(wanted['uom_id']) if wanted['uom_id'] else None
        # A line that rounds to the unit's zero says "buy nothing" — there
        # is nothing to buy (``none``). Skipping it keeps one unmeasurable
        # ingredient from failing the whole recipe's list.
        outcome, placed = await _put_on_list(
            db, org_id, list_id, wanted, uom, lines_by_key.get(key, []), lang
        )
        if outcome == 'new' and placed is not None:
            new_items.append(placed)
        elif outcome == 'raised' and placed is not None:
            raised_items.append(placed)
        elif outcome == 'listed':
            already_listed += 1
    added_items = await shopping_lists_api.add_items_async(
        db, list_id, new_items, org_id
    )
    return AddToShoppingListResponse(
        shopping_list_id=list_id,
        added_count=len(added_items),
        raised_count=len(raised_items),
        already_listed_count=already_listed,
        on_other_lists=await lines_listed_elsewhere(
            db, org_id, [*new_items, *raised_items], list_id=list_id
        ),
        list_name=shopping_list.name,
    )
