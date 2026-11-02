"""Put what one or more recipes still need onto a shopping list.

One code path serves both callers — the single-recipe button on a recipe
screen and the multi-recipe picker on a shopping list. Both answer the same
question ("what do I still have to buy for this?"), so both run the same
stock check, the same merge and the same skip-what-is-already-listed rule.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.contracts import ShoppingListItemCreateDTO
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.public_api import core_api
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

from ._constants import localized
from ._helpers import _round_shopping_qty
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
    recipes wanting flour buy flour once, with the amounts added up.

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
            else:
                merged[key] = {
                    'name': ing.name,
                    'quantity': quantity,
                    'uom_id': ing.required_uom_id,
                    'recipe_name': recipe.name,
                }

    return merged, recipe_names


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

    if shopping_list_id:
        shopping_list = await shopping_lists_api.get_shopping_list_async(
            db, shopping_list_id, org_id
        )
        if shopping_list is None:
            raise NotFoundException('shopping_list')
        list_id = shopping_list.id
        # Re-adding must not duplicate rows (match by name + uom).
        existing_items = await shopping_lists_api.get_list_items_async(
            db, list_id, org_id
        )
        existing_keys = {
            (item.name.strip().lower(), item.uom_id) for item in existing_items
        }
        wanted = len(merged)
        merged = {k: v for k, v in merged.items() if k not in existing_keys}
        # What is missing but already on the list: a second press added
        # nothing and said "Added 0 items", which reads as "nothing was
        # missing" or "it failed" — the count lets the screen say which.
        already_listed = wanted - len(merged)
    else:
        shopping_list = await shopping_lists_api.create_shopping_list_async(
            db,
            org_id=org_id,
            created_by=user_id,
            name=list_name or localized(_DEFAULT_LIST_NAME_LABELS, lang),
            lang=lang,
        )
        list_id = shopping_list.id
        already_listed = 0

    # The rounding reads the unit's own step, so the unit has to be
    # resolved before a line is rounded — once for the whole page, the way
    # the meal-plan path builds its map: a loop of get_async made the query
    # count grow with the number of merged lines (a recipe may name a
    # hundred ingredients).
    uoms_by_id = {
        uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    items: list[ShoppingListItemCreateDTO] = []
    for line in merged.values():
        uom = uoms_by_id.get(line['uom_id']) if line['uom_id'] else None
        qty = _round_shopping_qty(line['quantity'], uom)
        if qty <= 0:
            # A line that rounds to the unit's zero says "buy nothing" —
            # there is nothing to buy. Skipping it keeps one unmeasurable
            # ingredient from failing the whole recipe's list.
            continue
        items.append(
            ShoppingListItemCreateDTO(
                name=line['name'],
                quantity=qty,
                uom_id=line['uom_id'],
                notes=localized(_SHOPPING_NOTE_LABELS, lang, name=line['recipe_name']),
                note_data={'for_recipe': line['recipe_name']},
                source='recipe',
            )
        )
    added_items = await shopping_lists_api.add_items_async(db, list_id, items, org_id)
    return AddToShoppingListResponse(
        shopping_list_id=list_id,
        added_count=len(added_items),
        already_listed_count=already_listed,
        list_name=shopping_list.name,
    )
