"""A millilitre line on a bottled product is not that many bottles.

A recipe line of 30 ml of olive oil linked to a 750 g bottle used to
contribute 30 x 750 g = 22.5 kg of oil — the stew reported about 50,000
kcal per serving. The package weight answers "what does one whole package
weigh", and a millilitre is not a package: the multiplication ignored the
line's own unit and read the quantity as a count of bottles.

A volume measure therefore answers through a density — 30 ml x 0.92 g/ml
= 27.6 g — and through nothing else. When the ingredient's name carries no
density the line is reported as not computable rather than weighed as
packages; the package weight keeps answering the counted line it belongs
to (one unit of a 500 g loaf is still 500 g).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.product_template_metadata import set_template_nutrition
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.models.user import User
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.recipes.nutrition_service import get_recipe_nutrition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    organization = Organization(
        name='Millilitre Line Org', enabled_modules=['core', 'recipes']
    )
    real_async_db_session.add(organization)
    await real_async_db_session.flush()
    return organization


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        org,
        email='millilitre-line@example.com',
        role='admin',
    )


async def _uom_id(db: AsyncSession, symbol: str) -> UUID:
    return (await db.execute(select(Uom.id).where(Uom.symbol == symbol))).scalar_one()


async def _bottled_product(
    db: AsyncSession, org: Organization, name: str
) -> ProductTemplate:
    """A 750 g bottle carrying its own per-100 g nutrition figures."""
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        weight_value=Decimal('750'),
        weight_uom_id=await _uom_id(db, 'g'),
    )
    db.add(template)
    await db.flush()
    set_template_nutrition(template, {'calories_kcal': 884.0, 'fat_g': 100.0})
    await db.flush()
    return template


async def _single_serving_recipe(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    recipe_name: str,
    ingredient_name: str,
    quantity: str,
    uom_symbol: str,
    template: ProductTemplate,
) -> Recipe:
    recipe = Recipe(
        organization_id=org.id,
        name=recipe_name,
        servings=1,
        created_by=user.id,
    )
    db.add(recipe)
    await db.flush()
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            name=ingredient_name,
            quantity=Decimal(quantity),
            uom_id=await _uom_id(db, uom_symbol),
            template_id=template.id,
            sort_order=0,
        )
    )
    await db.flush()
    await db.refresh(recipe, ['ingredients'])
    return recipe


@pytest.mark.parametrize(
    ('uom_symbol', 'quantity'),
    [('ml', '30'), ('l', '0.03')],
)
async def test_thirty_millilitres_of_oil_are_28_grams_not_22_and_a_half_kilograms(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    uom_symbol: str,
    quantity: str,
) -> None:
    """30 ml against a 750 g bottle is 27.6 g of oil, not 30 bottles of it."""
    bottle = await _bottled_product(real_async_db_session, org, 'Olive oil bottle')
    recipe = await _single_serving_recipe(
        real_async_db_session,
        org,
        user,
        recipe_name='Spaghetti with garlic and oil',
        ingredient_name='Olive oil',
        quantity=quantity,
        uom_symbol=uom_symbol,
        template=bottle,
    )

    result = await get_recipe_nutrition(
        real_async_db_session, recipe, org.id, recipe.servings
    )

    # 30 ml x 0.92 g/ml = 27.6 g. The 100 g of fat per 100 g reads the
    # grams straight back out of the macro sum; 22.5 kg of oil would show
    # up here as 22,500 g of fat.
    assert result['total']['fat_g'] == pytest.approx(27.6, abs=0.01)
    assert result['total']['calories_kcal'] == pytest.approx(243.98, abs=0.1)
    assert result['per_serving'] == result['total']
    assert result['warnings'] == []
    assert result['coverage'] == 1.0


async def test_a_volume_line_with_no_density_is_reported_not_computable(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
) -> None:
    """No density to convert with means "not computable", never a package count."""
    bottle = await _bottled_product(real_async_db_session, org, 'Extract bottle')
    recipe = await _single_serving_recipe(
        real_async_db_session,
        org,
        user,
        recipe_name='Vanilla syrup',
        ingredient_name='Vanilla extract',
        quantity='30',
        uom_symbol='ml',
        template=bottle,
    )

    result = await get_recipe_nutrition(
        real_async_db_session, recipe, org.id, recipe.servings
    )

    assert result['total'] == {}
    assert result['warnings'] == ['Vanilla extract: no weight data, nutrition skipped']
    assert result['ingredients'][0]['has_data'] is False
    assert 'Vanilla extract' in result['missing_nutrition']
