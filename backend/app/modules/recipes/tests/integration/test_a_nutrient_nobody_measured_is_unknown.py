"""A nutrient nobody measured is unknown on the recipe, not 0 g.

A rice dish where only the chicken had values read "Carbs 0.0g" on its page,
while the meal plan printed "–" for the same recipe. Chicken has no carbs and
the rice, where the carbs are, had no data: the sum says nothing about them.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.product_template_metadata import set_template_nutrition
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.models.user import User
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.recipes.nutrition_service import get_recipe_nutrition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

CHICKEN = {'calories_kcal': 165.0, 'protein_g': 31.0, 'fat_g': 3.6, 'carbs_g': 0.0}


async def _product(
    db: AsyncSession,
    org: Organization,
    grams: UUID,
    name: str,
    values: dict[str, float],
) -> UUID:
    template = ProductTemplate(organization_id=org.id, name=name, uom_id=grams)
    db.add(template)
    await db.flush()
    set_template_nutrition(template, values)
    await db.flush()
    return template.id


async def _recipe(
    db: AsyncSession,
    org: Organization,
    user: User,
    grams: UUID,
    lines: list[tuple[str, UUID]],
) -> Recipe:
    recipe = Recipe(
        organization_id=org.id, name='Fried rice', servings=2, created_by=user.id
    )
    db.add(recipe)
    await db.flush()
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


async def test_a_zero_with_an_unmeasured_ingredient_is_unknown(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org = async_test_household
    grams = (await db.execute(select(Uom.id).where(Uom.symbol == 'g'))).scalar_one()
    chicken = await _product(db, org, grams, 'QA chicken', CHICKEN)
    rice = await _product(db, org, grams, 'QA rice', {})
    recipe = await _recipe(
        db, org, async_test_user, grams, [('QA chicken', chicken), ('QA rice', rice)]
    )

    result = await get_recipe_nutrition(db, recipe, org.id, recipe.servings)

    assert result['per_serving']['carbs_g'] is None
    assert result['total']['carbs_g'] is None
    # What was measured stands: the coverage line says it is partial.
    assert result['per_serving']['protein_g'] == pytest.approx(15.5)
    assert result['coverage'] == 0.5


async def test_a_zero_every_ingredient_vouches_for_stays_a_zero(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org = async_test_household
    grams = (await db.execute(select(Uom.id).where(Uom.symbol == 'g'))).scalar_one()
    chicken = await _product(db, org, grams, 'QA chicken', CHICKEN)
    recipe = await _recipe(db, org, async_test_user, grams, [('QA chicken', chicken)])

    result = await get_recipe_nutrition(db, recipe, org.id, recipe.servings)

    assert result['per_serving']['carbs_g'] == 0
    assert result['total']['carbs_g'] == 0
