from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from app.core.product_template_metadata import get_template_nutrition
from app.modules.recipes.defaults_service import lookup_default
from app.modules.recipes.models import Recipe

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# Food densities — domain input for the one conversion service: a volume
# measure becomes grams only through a density, and the density belongs to
# the ingredient, not to the unit table.
_DENSITY_G_PER_ML: dict[str, Decimal] = {
    'water': Decimal('1.00'),
    'milk': Decimal('1.03'),
    'cream': Decimal('1.01'),
    'oil': Decimal('0.92'),
    'olive oil': Decimal('0.92'),
    'vegetable oil': Decimal('0.92'),
    'sunflower oil': Decimal('0.92'),
    'coconut oil': Decimal('0.92'),
    'sesame oil': Decimal('0.92'),
    'honey': Decimal('1.42'),
    'maple syrup': Decimal('1.37'),
    'vinegar': Decimal('1.01'),
    'soy sauce': Decimal('1.18'),
    'wine': Decimal('0.99'),
    'beer': Decimal('1.01'),
    'juice': Decimal('1.04'),
    'orange juice': Decimal('1.04'),
    'lemon juice': Decimal('1.03'),
    'flour': Decimal('0.55'),
    'sugar': Decimal('0.85'),
    'butter': Decimal('0.96'),
    'melted butter': Decimal('0.96'),
    'yogurt': Decimal('1.03'),
    'buttermilk': Decimal('1.03'),
}

_MACRO_ALIASES: dict[str, list[str]] = {
    'calories_kcal': ['calories_kcal', 'calories', 'energy_kcal'],
    'protein_g': ['protein_g', 'proteins'],
    'fat_g': ['fat_g', 'fat'],
    'carbs_g': ['carbs_g', 'carbohydrates'],
    'fiber_g': ['fiber_g', 'fiber'],
    'sugar_g': ['sugar_g', 'sugars'],
    'salt_g': ['salt_g', 'salt'],
}


async def _canonical_measure(
    db: 'AsyncSession',
    quantity: Decimal,
    uom: Any,
) -> tuple[Decimal, str] | None:
    """Restate *quantity* in its unit's canonical measure via the core converter.

    The one conversion mechanism every mass/volume answer goes through —
    the private tables this module used to carry had an ounce of 28.35
    against the catalogue's 28.3495. ``None`` means the measures don't
    meet; never a silently unchanged quantity.
    """
    from app.core.public_api import core_api

    if uom is None:
        return None
    return await core_api.uoms.to_canonical_measure_async(db, quantity, uom)


def _lookup_density(ingredient_name: str) -> Decimal | None:
    name_lower = ingredient_name.lower().strip()
    if name_lower in _DENSITY_G_PER_ML:
        return _DENSITY_G_PER_ML[name_lower]
    for key, density in _DENSITY_G_PER_ML.items():
        if key in name_lower:
            return density
    return None


def _add_summary(
    acc: dict[str, float | None], contrib: dict[str, float | None]
) -> None:
    for key, value in contrib.items():
        if value is not None:
            if key in acc:
                existing = acc[key]
                if existing is not None:
                    acc[key] = existing + value
                # else: acc[key] is None, just replace it with the new value
                else:
                    acc[key] = value
            else:
                acc[key] = value


def _scale_nutrition(
    nutrition_per_100g: dict[str, float | None], grams: Decimal
) -> dict[str, float | None]:
    factor = float(grams) / 100.0
    result: dict[str, float | None] = {}
    for key, aliases in _MACRO_ALIASES.items():
        value = None
        for alias in aliases:
            v = nutrition_per_100g.get(alias)
            if v is not None:
                value = v
                break
        if value is not None:
            result[key] = round(float(value) * factor, 2)
    return result


_NEGLIGIBLE_THRESHOLD = Decimal('0.02')


async def _compute_total_mass_g(
    db: 'AsyncSession', recipe: Recipe, multiplier: Decimal
) -> Decimal:
    """Sum up mass (in grams) of all ingredients that have a mass UoM."""
    total = Decimal('0')
    for ing in recipe.ingredients:
        qty = Decimal(str(ing.quantity)) * multiplier
        measure = await _canonical_measure(db, qty, ing.uom)
        if measure is not None and measure[1] == 'g':
            total += measure[0]
    return total


def _default_to_nutrition_info(default: Any) -> dict[str, float]:
    """Read a defaults-table row into the macro dict shape used everywhere."""
    fields = (
        ('calories_kcal', default.calories_kcal),
        ('protein_g', default.protein_g),
        ('fat_g', default.fat_g),
        ('carbs_g', default.carbs_g),
        ('fiber_g', default.fiber_g),
        ('sugar_g', default.sugar_g),
        ('salt_g', default.salt_g),
    )
    return {key: float(value) for key, value in fields if value is not None}


async def _resolve_ingredient_nutrition(
    db: 'AsyncSession',
    ingredient: Any,
    stock: Any,
    organization_id: UUID,
    lang: str,
) -> tuple[dict[str, float] | None, Any]:
    """Find the macros for one ingredient, and the template they came from.

    Three sources in order of authority: the linked product, the product the
    ingredient resolves to in stock, and finally the defaults table (or the
    recipe's own per-100g figure). ``None`` means none of them knew.
    """
    from app.core.public_api import core_api

    from ._availability import measures_meet, resolve_template

    template = ingredient.template

    if not template or not get_template_nutrition(template):
        if ingredient.template_id and template is None:
            template = await core_api.product_templates.get_with_uom_async(
                db, organization_id, ingredient.template_id
            )

    if not template or not get_template_nutrition(template):
        # No hard link, or one whose product carries no nutrition data.
        # The product this ingredient actually resolves to knows more
        # than a generic default looked up from the name alone, so it
        # comes first and the defaults stay the last resort — but only a
        # product the availability comparison accepts: a name match it
        # refuses is not what the line stands for.
        matched = resolve_template(ingredient, stock)
        if (
            matched is not None
            and get_template_nutrition(matched)
            and (
                matched.id == ingredient.template_id
                or measures_meet(ingredient, matched, stock)
            )
        ):
            template = matched

    if template and get_template_nutrition(template):
        return get_template_nutrition(template) or {}, template

    default = await lookup_default(
        db, ingredient.name, lang=lang, org_id=organization_id
    )
    if default:
        return _default_to_nutrition_info(default), template
    if ingredient.calories_kcal_per_100g is not None:
        return {'calories_kcal': float(ingredient.calories_kcal_per_100g)}, template
    return None, template


async def _resolve_grams(
    db: 'AsyncSession',
    ingredient: Any,
    template: Any,
    required_qty: Decimal,
    uom: Any,
    ingredient_mass_g: Decimal | None,
    organization_id: UUID,
) -> Decimal | None:
    """How many grams this ingredient contributes, if that is knowable.

    The order is the answer's authority: a mass unit answers directly, a
    volume only ever through a density, and only what neither measure is
    — a counted or unitless line — falls back to the product's own
    package weight. The package weight is what a whole package weighs,
    and asked first it read 30 ml against a 750 g bottle as 30 bottles —
    22.5 kg of oil. A volume with no density to convert through is not
    computable — never a quantity of packages.
    """
    from app.core.public_api import core_api

    if ingredient_mass_g is not None:
        return ingredient_mass_g

    measure = await _canonical_measure(db, required_qty, uom)
    if measure is not None and measure[1] == 'ml':
        density = _lookup_density(ingredient.name)
        return measure[0] * density if density is not None else None

    if template is not None and template.weight_value:
        weight_uom = None
        if template.weight_uom_id:
            weight_uom = await core_api.uoms.get_async(
                db, template.weight_uom_id, organization_id
            )
        single_weight_measure = await _canonical_measure(
            db, Decimal(str(template.weight_value)), weight_uom
        )
        if single_weight_measure is not None and single_weight_measure[1] == 'g':
            return required_qty * single_weight_measure[0]

    return None


def _ingredient_row(
    ingredient: Any,
    required_qty: Decimal,
    uom_symbol: str | None,
    *,
    is_negligible: bool,
    nutrition: dict[str, float | None] | None,
) -> dict[str, Any]:
    """One entry of the per-ingredient breakdown; ``nutrition=None`` means no data."""
    return {
        'ingredient_name': ingredient.name,
        'quantity': float(required_qty),
        'uom': uom_symbol,
        'has_data': nutrition is not None,
        'negligible': is_negligible,
        'nutrition': nutrition,
    }


def _round_totals(
    total: dict[str, float | None], servings: Decimal
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """Split the accumulated macros into per-serving and total, both rounded.

    ``servings`` is the exact number of servings that were cooked, not the
    rounded count the response shows: a 1.4x cook of a four-portion recipe is
    5.6 servings of food, and dividing by the 6 shown instead would report
    every per-serving figure against the wrong number of mouths.
    """
    per_serving: dict[str, float | None] = {}
    total_rounded: dict[str, float | None] = {}
    for k, v in total.items():
        if v is not None:
            per_serving[k] = round(v / float(servings), 2)
            total_rounded[k] = round(v, 2)
        else:
            per_serving[k] = None
            total_rounded[k] = None
    return per_serving, total_rounded


def _unknown_unless_measured(
    figures: dict[str, float | None],
    total: dict[str, float | None],
    ingredients: list[dict[str, Any]],
) -> dict[str, float | None]:
    """Blank a figure whose sum is 0 while some ingredient has no value for it.

    Chicken with 0 g of carbs and rice with no data sum to 0 g, and the rice is
    where the carbs are: that 0 is the absence of a measurement. A 0 every
    ingredient vouches for stays. A sum above 0 stands, with the coverage line
    saying it is partial. The meal plan's daily row applies the same rule.
    """
    counted = [row for row in ingredients if not row['negligible']]
    return {
        key: None
        if total[key] == 0
        and any((row['nutrition'] or {}).get(key) is None for row in counted)
        else value
        for key, value in figures.items()
    }


async def get_recipe_nutrition(
    db: 'AsyncSession',
    recipe: Recipe,
    organization_id: UUID,
    servings_requested: int | Decimal,
    lang: str = 'en',
    scale: Decimal | None = None,
) -> dict[str, Any]:
    from ._availability import build_stock_context

    stock = await build_stock_context(db, list(recipe.ingredients), organization_id)

    from ._scaling import resolve_multiplier, rounded_servings, serving_equivalent

    multiplier = resolve_multiplier(recipe.servings, servings_requested, scale)
    exact_servings = serving_equivalent(recipe.servings, multiplier)
    total_mass_g = await _compute_total_mass_g(db, recipe, multiplier)
    total: dict[str, float | None] = {}
    ingredients_out = []
    missing_nutrition: list[str] = []
    warnings: list[str] = []
    has_data_count = 0
    non_negligible_count = 0
    generic_values = False

    for ingredient in recipe.ingredients:
        required_qty = Decimal(str(ingredient.quantity)) * multiplier
        uom_symbol = ingredient.uom.symbol if ingredient.uom else None
        mass_measure = await _canonical_measure(db, required_qty, ingredient.uom)
        ingredient_mass_g = (
            mass_measure[0] if mass_measure and mass_measure[1] == 'g' else None
        )
        is_negligible = (
            ingredient_mass_g is not None
            and total_mass_g > 0
            and ingredient_mass_g / total_mass_g < _NEGLIGIBLE_THRESHOLD
        )
        if not is_negligible:
            non_negligible_count += 1

        skipped = _ingredient_row(
            ingredient,
            required_qty,
            uom_symbol,
            is_negligible=is_negligible,
            nutrition=None,
        )

        nutrition_info, template = await _resolve_ingredient_nutrition(
            db, ingredient, stock, organization_id, lang
        )
        if nutrition_info is None:
            if not is_negligible:
                missing_nutrition.append(ingredient.name)
            ingredients_out.append(skipped)
            continue

        grams = await _resolve_grams(
            db,
            ingredient,
            template,
            required_qty,
            ingredient.uom,
            ingredient_mass_g,
            organization_id,
        )
        if grams is None:
            if not is_negligible:
                missing_nutrition.append(ingredient.name)
                warnings.append(f'{ingredient.name}: no weight data, nutrition skipped')
            ingredients_out.append(skipped)
            continue

        contrib = _scale_nutrition(cast(dict[str, float | None], nutrition_info), grams)
        if not contrib:
            if not is_negligible:
                missing_nutrition.append(ingredient.name)
            ingredients_out.append(skipped)
            continue

        _add_summary(total, contrib)
        if not is_negligible:
            has_data_count += 1
        # A figure that came from no product, only from the name, is generic.
        if not (template and get_template_nutrition(template)):
            generic_values = True

        ingredients_out.append(
            _ingredient_row(
                ingredient,
                required_qty,
                uom_symbol,
                is_negligible=is_negligible,
                nutrition=contrib,
            )
        )

    coverage = has_data_count / non_negligible_count if non_negligible_count else 1.0
    per_serving, total_rounded = _round_totals(total, exact_servings)

    return {
        'recipe_id': recipe.id,
        'servings': rounded_servings(exact_servings),
        'scale': float(multiplier),
        'per_serving': _unknown_unless_measured(
            per_serving, total_rounded, ingredients_out
        ),
        'total': _unknown_unless_measured(
            total_rounded, total_rounded, ingredients_out
        ),
        # The sums as they stand, for the meal plan: it asks whether a recipe
        # knows a nutrient at all, and decides a day's zeroes across its dishes.
        'measured_sums': total_rounded,
        'ingredients': ingredients_out,
        'coverage': round(coverage, 2),
        'missing_nutrition': missing_nutrition,
        'warnings': warnings,
        'generic_values': generic_values,
    }
