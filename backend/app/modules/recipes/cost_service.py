"""Recipe estimates use the shared Core stock-unit cost policy.

Priced layers precede current supplier offers. The recipe's own manually
entered ingredient price is its final fallback when the shared product price
is unknown. Quantities are converted to stock units before applying a rate.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UomDTO
from app.core.cost_estimates import UnitCostEstimate
from app.core.money import quantise
from app.core.public_api import core_api

from ._availability import StockContext, build_stock_context, resolve_template
from ._helpers import display_servings
from ._uom_helpers import convert_qty_for_template

if TYPE_CHECKING:
    from app.modules.recipes.models import Recipe


# Price provenance kept compatible with the recipe response.
_PriceSource = str  # 'avco' | 'supplier' | 'ingredient' | 'none'


async def get_recipe_cost(
    db: AsyncSession,
    recipe: Recipe,
    org_id: UUID,
    servings: int | Decimal,
) -> dict[str, Any]:
    """Estimate recipe cost for the given serving count.

    Returns a dict matching the ``RecipeCost`` schema with an extra
    ``price_source`` per ingredient (avco | supplier | ingredient | none)
    to help the UI display the price provenance.
    """
    from ._scaling import resolve_multiplier

    scale = resolve_multiplier(recipe.servings, servings, None)

    # Org currency is the implicit currency for layer-average-sourced prices.
    org = await core_api.organizations.get_async(db, org_id)
    org_currency = org.currency if org and org.currency else None

    ingredient_results: list[dict[str, Any]] = []
    total_cost = Decimal('0')
    currencies: set[str] = set()
    missing_cost: list[str] = []
    costed_count = 0
    total_ingredients = 0

    context = await build_stock_context(db, list(recipe.ingredients), org_id)
    uoms_by_id = {
        uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }

    templates = [
        resolve_template(ingredient, context) for ingredient in recipe.ingredients
    ]
    estimates = await core_api.valuation.estimate_unit_cost_async(
        db, org_id, [template.id for template in templates if template is not None]
    )

    for ingredient in recipe.ingredients:
        # Every ingredient counts, priced or not. Skipping the unpriceable
        # ones before this line reported full coverage over one costed
        # ingredient out of six — worse than no estimate, because it looked
        # like a complete one.
        total_ingredients += 1

        required_qty = Decimal(str(ingredient.quantity)) * scale
        # Read the unit from the batch the context already loaded rather
        # than from the relationship — one query for the whole request, and
        # no dependence on how the caller loaded the recipe.
        ingredient_uom = (
            uoms_by_id.get(ingredient.uom_id) if ingredient.uom_id else None
        )
        uom_symbol = ingredient_uom.symbol if ingredient_uom else None

        ingredient_cost, currency, source = _ingredient_cost(
            org_currency,
            ingredient,
            required_qty,
            ingredient_uom,
            context,
            uoms_by_id,
            estimates,
        )

        if ingredient_cost is None:
            missing_cost.append(ingredient.name)
            ingredient_results.append(
                {
                    'ingredient_name': ingredient.name,
                    'quantity': float(required_qty),
                    'uom': uom_symbol,
                    'estimated_cost': None,
                    'currency': None,
                    'has_price_data': False,
                    'price_source': source,
                }
            )
            continue

        # Currency mix check — shared product prices are in house money;
        # manually priced ingredients may name another currency.
        if currency:
            currencies.add(currency)
            # Detect mix between this ingredient and the running set.
            if len(currencies) > 1:
                missing_cost.append(ingredient.name)
                ingredient_results.append(
                    {
                        'ingredient_name': ingredient.name,
                        'quantity': float(required_qty),
                        'uom': uom_symbol,
                        'estimated_cost': None,
                        'currency': currency,
                        'has_price_data': False,
                        'price_source': source,
                    }
                )
                continue

        costed_count += 1
        total_cost += ingredient_cost

        ingredient_results.append(
            {
                'ingredient_name': ingredient.name,
                'quantity': float(required_qty),
                'uom': uom_symbol,
                # Quantized in Decimal (HALF_UP, the house rule) before the
                # wire's float: round(float(...)) does the rounding in
                # binary, where 2.675 is 2.67499999....
                'estimated_cost': float(quantise(ingredient_cost)),
                'currency': currency,
                'has_price_data': True,
                'price_source': source,
            }
        )

    mixed = len(currencies) > 1
    coverage = costed_count / total_ingredients if total_ingredients > 0 else 0.0
    estimated = (
        float(quantise(total_cost)) if (costed_count > 0 and not mixed) else None
    )
    final_currency = currencies.pop() if len(currencies) == 1 else None

    return {
        'recipe_id': recipe.id,
        'servings': display_servings(servings),
        'estimated_cost': estimated,
        'currency': final_currency,
        'cost_coverage': round(coverage, 4),
        'mixed_currencies': mixed,
        'missing_cost_ingredients': missing_cost,
        'ingredients': ingredient_results,
    }


def _ingredient_cost(
    org_currency: str | None,
    ingredient: Any,
    required_qty: Decimal,
    ingredient_uom: UomDTO | None,
    context: StockContext,
    uoms_by_id: dict[UUID, UomDTO],
    estimates: dict[UUID, UnitCostEstimate],
) -> tuple[Decimal | None, str | None, _PriceSource]:
    """Cost this ingredient's requirement: its product's price, else its own.

    The price typed on the ingredient is the last tier. Every shared product
    price is a measurement (valuation or an offer), and the typed one
    is somebody's estimate, so it answers only when the product cannot.
    """
    cost, currency, source = _product_cost(
        ingredient,
        required_qty,
        ingredient_uom,
        context,
        uoms_by_id,
        estimates,
    )
    if cost is not None:
        return cost, currency, source
    own = _own_price_cost(ingredient, required_qty, ingredient_uom, org_currency)
    if own is not None:
        return own[0], own[1], 'ingredient'
    return cost, currency, source


def _own_price_cost(
    ingredient: Any,
    required_qty: Decimal,
    ingredient_uom: UomDTO | None,
    org_currency: str | None,
) -> tuple[Decimal, str | None] | None:
    """The requirement priced by the ingredient's own "price per unit".

    The editor asks for the price per the ingredient's own unit, so the
    quantity is multiplied as it stands.
    """
    if ingredient.price is None or ingredient.price < 0:
        return None
    if ingredient_uom is not None and ingredient.price_uom_id not in (
        None,
        ingredient_uom.id,
    ):
        # A price quoted in another unit than the line asks for: no honest
        # estimate without a conversion this field was never given.
        return None
    return (
        Decimal(str(ingredient.price)) * required_qty,
        ingredient.price_currency or org_currency,
    )


def _product_cost(
    ingredient: Any,
    required_qty: Decimal,
    ingredient_uom: UomDTO | None,
    context: StockContext,
    uoms_by_id: dict[UUID, UomDTO],
    estimates: dict[UUID, UnitCostEstimate],
) -> tuple[Decimal | None, str | None, _PriceSource]:
    """Cost this ingredient's requirement from its product, or None.

    The product comes from the shared matcher, so an ingredient typed by
    hand is priced like a linked one. The requirement is then converted
    into the unit the price is quoted in — prices are per stock unit, and
    multiplying a price per can by 400 grams values one tin of chickpeas
    at four hundred tins. When the two measures cannot meet, the
    ingredient is reported as unpriced: no estimate is honest, an estimate
    inflated a hundredfold is not.
    """
    template = resolve_template(ingredient, context)
    if template is None:
        return None, None, 'none'

    estimate = estimates.get(template.id, UnitCostEstimate())
    unit_price, currency = estimate.unit_cost, estimate.currency
    source = 'avco' if estimate.source == 'layers' else estimate.source
    if unit_price is None:
        return None, None, 'none'

    quantity = convert_qty_for_template(
        required_qty,
        ingredient_uom,
        uoms_by_id.get(template.uom_id) if template.uom_id else None,
        template,
        uoms_by_id,
    )
    if quantity is None:
        return None, currency, source
    return unit_price * quantity, currency, source
