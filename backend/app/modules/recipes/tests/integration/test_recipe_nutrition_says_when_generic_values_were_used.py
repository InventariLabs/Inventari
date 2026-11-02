"""A recipe's nutrition says whether any of its figures are generic values.

The estimate sits beside a note telling the reader where the values come
from. A line priced from the shipped ingredient dictionary ("roughly what is
in wheat flour") is a weaker figure than the label of the product on the
shelf, and the note can only say so when the calculation reports it.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.product_template_metadata import set_template_nutrition
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.models.user import User
from app.modules.recipes.models import (
    IngredientNutritionDefault,
    Recipe,
    RecipeIngredient,
)
from app.modules.recipes.nutrition_service import get_recipe_nutrition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _uom_id(db: AsyncSession, symbol: str) -> UUID:
    return (await db.execute(select(Uom.id).where(Uom.symbol == symbol))).scalar_one()


async def _recipe(
    db: AsyncSession,
    org: Organization,
    user: User,
    lines: list[tuple[str, UUID | None]],
) -> Recipe:
    """One serving; each line is 100 g of an ingredient, linked or not."""
    recipe = Recipe(
        organization_id=org.id, name='QA Mix', servings=1, created_by=user.id
    )
    db.add(recipe)
    await db.flush()
    grams = await _uom_id(db, 'g')
    for order, (name, template_id) in enumerate(lines):
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                name=name,
                quantity=Decimal('100'),
                uom_id=grams,
                template_id=template_id,
                sort_order=order,
            )
        )
    await db.flush()
    await db.refresh(recipe, ['ingredients'])
    return recipe


async def _product(db: AsyncSession, org: Organization, name: str) -> UUID:
    template = ProductTemplate(
        organization_id=org.id, name=name, uom_id=await _uom_id(db, 'g')
    )
    db.add(template)
    await db.flush()
    set_template_nutrition(template, {'calories_kcal': 364.0, 'protein_g': 10.0})
    await db.flush()
    return template.id


async def _generic_flour(db: AsyncSession) -> None:
    db.add(
        IngredientNutritionDefault(
            id=uuid4(),
            organization_id=None,
            lang='en',
            name='Wheat Flour',
            name_normalized='wheat flour',
            calories_kcal=Decimal('340'),
            protein_g=Decimal('10'),
            source='system',
            is_system=True,
        )
    )
    await db.flush()


async def test_a_line_filled_from_the_dictionary_is_reported_as_generic(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    await _generic_flour(db)
    recipe = await _recipe(
        db, async_test_household, async_test_user, [('Wheat Flour', None)]
    )

    result = await get_recipe_nutrition(
        db, recipe, async_test_household.id, recipe.servings
    )

    assert result['total']['calories_kcal'] == pytest.approx(340.0)
    assert result['generic_values'] is True


async def test_products_own_values_are_not_reported_as_generic(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    await _generic_flour(db)
    flour = await _product(db, async_test_household, 'Wheat Flour')
    recipe = await _recipe(
        db, async_test_household, async_test_user, [('Wheat Flour', flour)]
    )

    result = await get_recipe_nutrition(
        db, recipe, async_test_household.id, recipe.servings
    )

    assert result['total']['calories_kcal'] == pytest.approx(364.0)
    assert result['generic_values'] is False
