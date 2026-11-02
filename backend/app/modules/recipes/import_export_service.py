"""
Recipe import / export service.

Export formats:
  - json      : internal JSON format (version-stamped)
  - schema_org: Schema.org Recipe (https://schema.org/Recipe)

Import sources:
  - json : internal JSON format
  - url  : live URL, scraped by the Jina+LLM pipeline
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ProductTemplateCandidateDTO
from app.core.exceptions import ServiceRejectionError

from .models import Recipe
from .schemas import RecipeCreate, RecipeIngredientCreate
from .services import create_recipe

_EXPORT_VERSION = 1

# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------


def export_recipe_json(recipe: Recipe) -> dict[str, Any]:
    """Return a portable JSON dict for the given Recipe ORM object."""
    return {
        '_export_version': _EXPORT_VERSION,
        'name': recipe.name,
        'description': recipe.description,
        'instructions': recipe.instructions,
        'servings': recipe.servings,
        'prep_time_minutes': recipe.prep_time_minutes,
        'tags': recipe.tags or [],
        'is_favorite': recipe.is_favorite,
        'ingredients': [
            {
                'name': ing.name,
                'quantity': float(ing.quantity),
                'uom': ing.uom.symbol if ing.uom else None,
                'is_optional': ing.is_optional,
                'is_spice': ing.is_spice,
                'sort_order': ing.sort_order,
                # EU 1169/2011 allergen keys (own extension — Schema.org
                # has no allergen field, only diet types)
                'allergens': ing.allergens or [],
            }
            for ing in recipe.ingredients
        ],
    }


def export_recipe_schema_org(recipe: Recipe) -> dict[str, Any]:
    """Return Schema.org Recipe JSON-LD dict."""
    ingredients_text = [
        f'{float(ing.quantity)} {ing.uom.symbol if ing.uom else ""} {ing.name}'.strip()
        for ing in recipe.ingredients
    ]
    result: dict[str, Any] = {
        '@context': 'https://schema.org',
        '@type': 'Recipe',
        'name': recipe.name,
        'recipeYield': str(recipe.servings),
        'recipeIngredient': ingredients_text,
    }
    if recipe.description:
        result['description'] = recipe.description
    if recipe.instructions:
        result['recipeInstructions'] = recipe.instructions
    if recipe.prep_time_minutes:
        result['prepTime'] = f'PT{recipe.prep_time_minutes}M'
    if recipe.image_url:
        result['image'] = recipe.image_url
    if recipe.tags:
        result['keywords'] = ', '.join(recipe.tags)
    # Custom extension: Schema.org Recipe has no allergen field, so the
    # recipe-level union of EU 1169/2011 allergen keys is exposed under
    # a vendor-prefixed 'inventari:allergens' property.
    all_allergens = sorted(
        {a for ing in recipe.ingredients for a in (ing.allergens or [])}
    )
    if all_allergens:
        result['inventari:allergens'] = all_allergens
    return result


# ---------------------------------------------------------------------------
# Import helpers (JSON)
# ---------------------------------------------------------------------------


async def _parse_import_json(
    data: dict[str, Any],
    uom_resolver: Any | None = None,
) -> RecipeCreate:
    """Convert internal-format JSON dict to RecipeCreate schema.

    Resolves each ingredient's ``uom`` symbol (e.g. ``"kg"``, ``"pcs"``)
    to a ``uom_id`` via the optional async ``UomResolverAsync`` — without
    it the unit is silently dropped, which broke export→import round-trips.

    Raises ValueError for missing required fields.
    """
    name = data.get('name')
    if not name:
        raise ServiceRejectionError('recipe_import_name_required')

    raw_ings = data.get('ingredients') or []
    ingredients = []
    for idx, ing in enumerate(raw_ings):
        if not ing.get('name'):  # skip ingredients without a name
            continue
        uom_id = None
        # `uom` is the canonical field (written by export_recipe_json);
        # `unit` is accepted as a legacy alias from older import payloads.
        symbol = ing.get('uom') or ing.get('unit')
        if uom_resolver is not None and isinstance(symbol, str) and symbol.strip():
            uom_id = await uom_resolver.resolve(symbol)
        ingredients.append(
            RecipeIngredientCreate(
                name=ing.get('name', ''),
                quantity=ing.get('quantity', 1),
                uom_id=uom_id,
                is_optional=ing.get('is_optional', False),
                is_spice=ing.get('is_spice', False),
                sort_order=ing.get('sort_order', idx),
                allergens=ing.get('allergens') or [],
            )
        )

    return RecipeCreate(
        name=name,
        description=data.get('description'),
        instructions=data.get('instructions'),
        servings=data.get('servings', 1),
        prep_time_minutes=data.get('prep_time_minutes'),
        tags=data.get('tags') or [],
        is_favorite=data.get('is_favorite', False),
        ingredients=ingredients,
    )


def _raw_unit_symbols(data: dict[str, Any]) -> list[str | None]:
    """The unit strings of a JSON payload, aligned with the parsed ingredients.

    Same skip-empty-name order as ``_parse_import_json``.
    """
    symbols: list[str | None] = []
    for ing in data.get('ingredients') or []:
        if not ing.get('name'):
            continue
        symbol = ing.get('uom') or ing.get('unit')
        symbols.append(symbol if isinstance(symbol, str) and symbol.strip() else None)
    return symbols


def _refuse_lines_without_a_unit(
    recipe: RecipeCreate, raw_symbols: list[str | None] | None = None
) -> None:
    """Refuse an amount that names no unit the instance knows.

    "2 tbsp" saved as "2" reached the shopping list as "Soy sauce 2 —". The
    recipe form refuses such a line; this is the same refusal for a client
    that imports without the review screen.
    """
    for idx, ing in enumerate(recipe.ingredients):
        if ing.uom_id is not None:
            continue
        unit = raw_symbols[idx] if raw_symbols else None
        if unit:
            raise ServiceRejectionError(
                'recipe_import_unit_unknown', ingredient=ing.name, unit=unit
            )
        raise ServiceRejectionError('recipe_import_unit_missing', ingredient=ing.name)


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------


async def _namesakes_async(
    db: AsyncSession, org_id: UUID, recipe: RecipeCreate
) -> dict[str, ProductTemplateCandidateDTO]:
    """The products named exactly like the recipe's ingredients.

    A JSON import carries no links, and the review screen showed "Not
    matched" beside four ingredients whose names were the pantry products'
    own; the recipe then read them as "Similar" until each was linked by
    hand. An identical name is linked on the way in — the reader can still
    change it on the review screen.
    """
    from .template_matcher import match_identical_names_async

    return await match_identical_names_async(
        db, org_id, [ing.name for ing in recipe.ingredients]
    )


async def import_recipe(
    db: AsyncSession,
    import_format: str,
    org_id: UUID,
    user_id: UUID,
    *,
    data: dict[str, Any] | None = None,
    url: str | None = None,
    organization_settings: dict[str, Any] | None = None,
) -> Recipe:
    """Import a recipe and persist it.  Returns the new Recipe ORM object."""
    if import_format == 'json':
        if data is None:
            raise ServiceRejectionError('recipe_import_data_required')
        from app.core.uom_resolver import UomResolverAsync

        uom_resolver = UomResolverAsync(db, org_id)
        recipe_create = await _parse_import_json(data, uom_resolver)
        _refuse_lines_without_a_unit(recipe_create, _raw_unit_symbols(data))
        namesakes = await _namesakes_async(db, org_id, recipe_create)
        for ing in recipe_create.ingredients:
            if ing.template_id is None and ing.name in namesakes:
                ing.template_id = namesakes[ing.name].id
    elif import_format == 'url':
        if not url:
            raise ServiceRejectionError('recipe_import_url_required')
        from ._import_url_pipeline import _parse_import_url

        recipe_create = await _parse_import_url(
            url,
            db,
            org_id,
            user_id,
            organization_settings=organization_settings,
        )
        _refuse_lines_without_a_unit(recipe_create)
    else:
        raise ServiceRejectionError('unsupported_import_format', format=import_format)

    return await create_recipe(db, recipe_create, org_id, user_id)


# ---------------------------------------------------------------------------
# Import preview (parse without saving)
# ---------------------------------------------------------------------------


async def preview_import(
    db: AsyncSession,
    import_format: str,
    org_id: UUID,
    user_id: UUID,
    *,
    data: dict[str, Any] | None = None,
    url: str | None = None,
    organization_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse a recipe without persisting.  Returns a preview dict.

    The preview includes ``original_text`` for each ingredient so the user
    can compare the parsed result with the source.
    """
    from .schemas import PreviewIngredient

    if import_format == 'url':
        if not url:
            raise ServiceRejectionError('recipe_import_url_required')
        from ._import_url_pipeline import _preview_import_url

        preview = await _preview_import_url(
            url,
            db,
            org_id,
            user_id,
            organization_settings=organization_settings,
        )
    elif import_format == 'json':
        if data is None:
            raise ServiceRejectionError('recipe_import_data_required')
        from app.core.uom_resolver import UomResolverAsync

        uom_resolver = UomResolverAsync(db, org_id)
        recipe_create = await _parse_import_json(data, uom_resolver)
        raw_symbols = _raw_unit_symbols(data)
        namesakes = await _namesakes_async(db, org_id, recipe_create)
        preview = {
            'name': recipe_create.name,
            'description': recipe_create.description,
            'instructions': recipe_create.instructions,
            'servings': recipe_create.servings,
            'prep_time_minutes': recipe_create.prep_time_minutes,
            'image_source_url': None,
            'tags': recipe_create.tags or [],
            'ingredients': [
                PreviewIngredient(
                    name=ing.name,
                    quantity=float(ing.quantity),
                    uom_id=str(ing.uom_id) if ing.uom_id else None,
                    is_optional=ing.is_optional,
                    is_spice=ing.is_spice,
                    allergens=ing.allergens,
                    original_unit_text=raw_symbols[idx],
                    template_id=(
                        str(namesakes[ing.name].id) if ing.name in namesakes else None
                    ),
                    template_name=(
                        namesakes[ing.name].name if ing.name in namesakes else None
                    ),
                ).model_dump()
                for idx, ing in enumerate(recipe_create.ingredients)
            ],
        }
    else:
        raise ServiceRejectionError('unsupported_import_format', format=import_format)

    return preview
