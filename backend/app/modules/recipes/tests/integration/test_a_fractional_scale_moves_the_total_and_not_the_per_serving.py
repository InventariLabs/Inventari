"""A fractional multiplier has to survive into the response, not just the pot.

The recipe is written for four servings and cooked for one and a half times as
much. What comes out is 5.6 servings of food, and one number can no longer say
both things: ``servings`` stays an ``int`` and carries the rounded count every
existing client already renders, while ``scale`` carries the ratio the maths
was actually done in. Changing the type of ``servings`` would break every
consumer — the export and the print layout included — to buy one field.

The calories are where the split bites. Kcal per serving divided by
``servings_requested``, the rounded count, so one and a half times a
four-portion recipe reported per-serving figures a quarter too high: the pot
grew, the number of mouths grew with it, and the division pretended only the
pot had moved. Dividing by ``recipe.servings * multiplier`` keeps the
per-serving figures exactly where they were at scale 1, which is the whole
point of a multiplier — nobody's portion got any bigger.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.uom import Uom
from app.models.user import User
from app.modules.recipes._availability import get_recipe_availability
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.recipes.nutrition_service import get_recipe_nutrition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    organization = Organization(
        name='Four Portions Org', enabled_modules=['core', 'recipes']
    )
    real_async_db_session.add(organization)
    await real_async_db_session.flush()
    return organization


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        org,
        email='four-portions@example.com',
        role='admin',
    )


async def _flour_omelette(db: AsyncSession, org: Organization, user: User) -> Recipe:
    """A four-portion recipe: 200 g of flour at 100 kcal per 100 g.

    Per serving as written that is 50 kcal, and a multiplier must not move it.
    """
    grams = (await db.execute(select(Uom.id).where(Uom.symbol == 'g'))).scalar_one()
    recipe = Recipe(
        organization_id=org.id,
        name='Flour omelette',
        servings=4,
        created_by=user.id,
    )
    db.add(recipe)
    await db.flush()
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            name='Flour',
            quantity=Decimal('200'),
            uom_id=grams,
            calories_kcal_per_100g=Decimal('100'),
            sort_order=0,
        )
    )
    await db.flush()
    await db.refresh(recipe, ['ingredients'])
    return recipe


async def test_a_fractional_scale_moves_the_total_and_not_the_per_serving(
    real_async_db_session: AsyncSession, org: Organization, user: User
) -> None:
    recipe = await _flour_omelette(real_async_db_session, org, user)

    as_written = await get_recipe_nutrition(
        real_async_db_session, recipe, org.id, recipe.servings
    )
    one_and_a_half = await get_recipe_nutrition(
        real_async_db_session,
        recipe,
        org.id,
        recipe.servings,
        scale=Decimal('1.5'),
    )

    assert one_and_a_half['total'] == {
        key: round(value * 1.5, 2) if value is not None else None
        for key, value in as_written['total'].items()
    }
    assert one_and_a_half['per_serving'] == as_written['per_serving']
    assert one_and_a_half['scale'] == 1.5
    assert one_and_a_half['servings'] == 6


async def test_the_shown_servings_are_rounded_while_the_division_stays_exact(
    real_async_db_session: AsyncSession, org: Organization, user: User
) -> None:
    recipe = await _flour_omelette(real_async_db_session, org, user)

    as_written = await get_recipe_nutrition(
        real_async_db_session, recipe, org.id, recipe.servings
    )
    point_four = await get_recipe_nutrition(
        real_async_db_session,
        recipe,
        org.id,
        recipe.servings,
        scale=Decimal('1.4'),
    )

    # 4 x 1.4 is 5.6 servings of food, shown as 6 because servings stays int.
    assert point_four['servings'] == 6
    assert point_four['scale'] == 1.4
    # kcal per serving is per the 5.6 that were cooked, not the 6 that are
    # shown — dividing by 6 would report 46.67 instead of 50.
    assert point_four['per_serving'] == as_written['per_serving']


async def test_the_availability_answer_carries_the_multiplier_it_scaled_by(
    real_async_db_session: AsyncSession, org: Organization, user: User
) -> None:
    recipe = await _flour_omelette(real_async_db_session, org, user)

    answer = await get_recipe_availability(
        real_async_db_session,
        recipe,
        org.id,
        recipe.servings,
        scale=Decimal('1.4'),
    )

    assert answer.scale == 1.4
    assert answer.servings_requested == 6
