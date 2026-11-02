"""The price typed on an ingredient reaches the recipe's cost.

The field was saved and shown, and the cost counted only the prices of
products: an ingredient with a price and no product still read "no data", and
the empty section offered "Edit" as if typing a price would help. The price on
the ingredient is now the last tier, under every price a product has: stock
valuation or a supplier's offer.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.recipes.cost_service import get_recipe_cost
from app.modules.recipes.models.recipe import Recipe, RecipeIngredient
from app.services.valuation_service import ValuationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _recipe(
    db: AsyncSession,
    org: Organization,
    user: User,
    *ingredients: RecipeIngredient,
    servings: int = 1,
) -> Recipe:
    recipe = Recipe(
        organization_id=org.id,
        created_by=user.id,
        name=f'Own price {uuid4().hex[:6]}',
        servings=servings,
        ingredients=list(ingredients),
    )
    db.add(recipe)
    await db.commit()
    return recipe


async def test_an_ingredient_without_a_product_is_priced_by_its_own_price(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    recipe = await _recipe(
        real_async_db_session,
        async_test_household,
        async_test_user,
        RecipeIngredient(name='Saffron', quantity=Decimal('3'), price=Decimal('2.50')),
    )

    result = await get_recipe_cost(
        real_async_db_session, recipe, async_test_household.id, servings=1
    )

    assert result['estimated_cost'] == 7.5
    assert result['missing_cost_ingredients'] == []
    assert result['ingredients'][0]['price_source'] == 'ingredient'
    assert result['ingredients'][0]['has_price_data'] is True


async def test_the_price_follows_the_servings_asked_for(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    recipe = await _recipe(
        real_async_db_session,
        async_test_household,
        async_test_user,
        RecipeIngredient(name='Saffron', quantity=Decimal('3'), price=Decimal('2.50')),
        servings=2,
    )

    result = await get_recipe_cost(
        real_async_db_session, recipe, async_test_household.id, servings=4
    )

    assert result['estimated_cost'] == 15.0


async def test_a_price_a_product_has_beats_the_ingredients_own(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    template = ProductTemplate(
        organization_id=async_test_household.id,
        name='Flour',
        sku=f'SKU-OWN-{uuid4().hex[:8]}',
    )
    real_async_db_session.add(template)
    await real_async_db_session.flush()
    await ValuationService._record_receipt_async(
        real_async_db_session,
        template,
        Decimal('1000'),
        Decimal('4'),
        async_test_household.id,
    )
    recipe = await _recipe(
        real_async_db_session,
        async_test_household,
        async_test_user,
        RecipeIngredient(
            template_id=template.id,
            name='Flour',
            quantity=Decimal('2'),
            price=Decimal('99'),
        ),
    )

    result = await get_recipe_cost(
        real_async_db_session, recipe, async_test_household.id, servings=1
    )

    assert result['estimated_cost'] == 8.0
    assert result['ingredients'][0]['price_source'] == 'avco'


async def test_an_ingredient_with_no_price_anywhere_is_still_missing(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    recipe = await _recipe(
        real_async_db_session,
        async_test_household,
        async_test_user,
        RecipeIngredient(name='Water', quantity=Decimal('1')),
    )

    result = await get_recipe_cost(
        real_async_db_session, recipe, async_test_household.id, servings=1
    )

    assert result['estimated_cost'] is None
    assert result['missing_cost_ingredients'] == ['Water']
