"""Put what one or more recipes still need onto a shopping list.

One code path serves both callers — the single-recipe button on a recipe
screen and the multi-recipe picker on a shopping list. Both answer the same
question ("what do I still have to buy for this?"), so both run the same
stock check, the same merge and the same top-up rule for what is already
listed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from app.core.contracts import ShoppingListItemCreateDTO, ShoppingListItemDTO, UomDTO
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.public_api import core_api
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

from ._constants import localized
from ._helpers import _round_shopping_qty
from ._shopping_overlap import lines_listed_elsewhere
from ._shopping_rule import (
    load_exclusions,
    needs_buying,
    quantity_to_buy,
)
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
    """Aggregate what the given recipes still need, keyed by (name, unit).

    Returns the merged lines and the recipe names they came from — two
    recipes wanting flour buy flour once, with the amounts added up. Each
    line keeps what every recipe contributed (``by_recipe``), so a later
    press can tell what the recipes a line was not yet made for add.

    The amount is the *shortfall*: what the recipe asks for less what the
    shelf already holds, the same arithmetic the meal plan applies. The
    list used to ask for the whole recipe even with half of it in the
    cupboard. Lines the organization marked "Always at home" are left out,
    by product or by name, as the meal plan already did.
    """
    merged: dict[tuple[str, UUID | None], dict[str, Any]] = {}
    recipe_names: list[str] = []
    exclusions = await load_exclusions(db, org_id)

    for recipe_id in recipe_ids:
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)
        recipe_names.append(recipe.name)

        effective_servings = servings or recipe.servings
        if scale is not None:
            # A stated multiplier wins over a serving count, and multiplied
            # out it can be fractional — the availability math carries it
            # exactly.
            effective_servings = Decimal(recipe.servings) * scale
        avail = await get_recipe_availability(db, recipe, org_id, effective_servings)

        linked_template = {ing.id: ing.template_id for ing in recipe.ingredients}
        for ing in avail.ingredients:
            if not needs_buying(ing.status, ing.quantities_comparable):
                continue
            if exclusions.excludes(ing.name, linked_template.get(ing.ingredient_id)):
                continue
            quantity = quantity_to_buy(
                Decimal(str(ing.required_quantity)),
                Decimal(str(ing.available_quantity or 0)),
                comparable=ing.quantities_comparable,
            )
            if quantity is None or quantity <= 0:
                continue
            key = (ing.name.strip().lower(), ing.required_uom_id)
            if key in merged:
                merged[key]['quantity'] += quantity
                if recipe.name not in merged[key]['recipes']:
                    merged[key]['recipes'].append(recipe.name)
                by_recipe = merged[key]['by_recipe']
                by_recipe[recipe.name] = by_recipe.get(recipe.name, Decimal(0)) + (
                    quantity
                )
            else:
                merged[key] = {
                    'name': ing.name,
                    'quantity': quantity,
                    'uom_id': ing.required_uom_id,
                    'recipes': [recipe.name],
                    'by_recipe': {recipe.name: quantity},
                }

    return merged, recipe_names


def _recipe_note(recipes: list[str], lang: Language) -> str:
    return localized(_SHOPPING_NOTE_LABELS, lang, name=', '.join(recipes))


def _recipe_note_data(recipes: list[str]) -> dict[str, Any]:
    # ``for_recipe`` is what the list renders; ``for_recipes`` keeps the
    # names apart, so a later press knows which recipes a line was made for.
    return {'for_recipe': ', '.join(recipes), 'for_recipes': recipes}


def _recipes_of(line: ShoppingListItemDTO) -> list[str]:
    data = line.note_data or {}
    named = data.get('for_recipes')
    if isinstance(named, list):
        return [str(name) for name in named]
    single = data.get('for_recipe')
    return [single] if isinstance(single, str) else []


async def _put_on_list(
    db: AsyncSession,
    org_id: UUID,
    list_id: UUID,
    item: ShoppingListItemCreateDTO,
    by_recipe: dict[str, Decimal],
    uom: UomDTO | None,
    lines: list[ShoppingListItemDTO],
    lang: Language,
) -> tuple[Literal['new', 'raised', 'listed'], ShoppingListItemCreateDTO]:
    """Decide what one wanted line does to the *lines* the list has for it.

    ``new``: write the returned line. ``raised``: an open line of these
    recipes was topped up in place, and the returned line says by how much it
    now asks. ``listed``: the list already covers it, nothing is written.

    A line a recipe wrote carries the recipes it was made for. The same
    recipes pressed again are covered, so a second press stays a no-op; a
    recipe no line was made for adds what *it* needs on top (``by_recipe``
    holds each recipe's share, so one the line already covers is not counted
    again), on the open line or as a new line when the earlier one is
    already bought. Lines no
    recipe wrote (typed by hand, from a meal plan) carry no such record, so
    the list asks for what the sum of them covers and a larger need adds
    only the difference.
    """
    if not lines:
        return 'new', item
    recipe_lines = [line for line in lines if line.source == 'recipe']
    if not recipe_lines:
        shortfall = item.quantity - sum((line.quantity for line in lines), Decimal(0))
        if shortfall <= 0:
            return 'listed', item
        return 'new', item.model_copy(update={'quantity': shortfall})
    covered = {name for line in recipe_lines for name in _recipes_of(line)}
    fresh = [name for name in by_recipe if name not in covered]
    if not fresh:
        return 'listed', item
    needed = _round_shopping_qty(sum((by_recipe[n] for n in fresh), Decimal(0)), uom)
    if needed <= 0:
        return 'listed', item
    open_line = next((line for line in recipe_lines if not line.is_purchased), None)
    if open_line is None:
        return 'new', item.model_copy(
            update={
                'quantity': needed,
                'notes': _recipe_note(fresh, lang),
                'note_data': _recipe_note_data(fresh),
            }
        )
    names = [*_recipes_of(open_line), *fresh]
    quantity = open_line.quantity + needed
    raised = await shopping_lists_api.raise_item_quantity_async(
        db,
        list_id,
        open_line.id,
        quantity,
        org_id,
        notes=_recipe_note(names, lang),
        note_data={**(open_line.note_data or {}), **_recipe_note_data(names)},
    )
    if not raised:
        return 'listed', item
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

    if not merged:
        if not shopping_list_id:
            raise ServiceRejectionError('no_missing_ingredients')
        return AddToShoppingListResponse(
            shopping_list_id=shopping_list_id,
            added_count=0,
        )

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
    items: list[
        tuple[ShoppingListItemCreateDTO, dict[str, Decimal], UomDTO | None]
    ] = []
    for line in merged.values():
        uom = uoms_by_id.get(line['uom_id']) if line['uom_id'] else None
        qty = _round_shopping_qty(line['quantity'], uom)
        if qty <= 0:
            # A line that rounds to the unit's zero says "buy nothing" —
            # there is nothing to buy. Skipping it keeps one unmeasurable
            # ingredient from failing the whole recipe's list.
            continue
        items.append(
            (
                ShoppingListItemCreateDTO(
                    name=line['name'],
                    quantity=qty,
                    uom_id=line['uom_id'],
                    notes=_recipe_note(line['recipes'], lang),
                    note_data=_recipe_note_data(line['recipes']),
                    source='recipe',
                ),
                line['by_recipe'],
                uom,
            )
        )

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
    for item, by_recipe, uom in items:
        lines = lines_by_key.get((item.name.strip().lower(), item.uom_id), [])
        outcome, placed = await _put_on_list(
            db, org_id, list_id, item, by_recipe, uom, lines, lang
        )
        if outcome == 'new':
            new_items.append(placed)
        elif outcome == 'raised':
            raised_items.append(placed)
        else:
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
