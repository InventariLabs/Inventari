"""A product the shelf comparison refuses does not lend a recipe its macros.

A recipe line "Salt, 1" with no unit and no linked product reported 884
kcal per serving at full coverage: the name matcher accepts a shared stem,
so "Salt" stood for "Salted Potato Crisps", and the unitless 1 was read as
one 165 g bag of them. The availability card on the same page refused that
very match — "13 pcs. in stock, recipe needs 1, cannot compare" — while
the nutrition estimate silently summed it.

The estimate now borrows a matched product only where the availability
comparison accepts it; a refused match leaves the line out with the usual
missing-nutrition entry. A match whose measures meet keeps lending.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.product_template_metadata import set_template_nutrition
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.recipes._availability import get_recipe_availability
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.recipes.nutrition_service import get_recipe_nutrition
from tests.integration._shelf import anchor_pending_records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _uom_id(db: AsyncSession, symbol: str) -> UUID:
    return (await db.execute(select(Uom.id).where(Uom.symbol == symbol))).scalar_one()


async def _stock_bags(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    *,
    name: str,
    grams_per_bag: str,
    kcal_per_100g: float,
) -> ProductTemplate:
    """Thirteen bags on the shelf, counted in pieces, each of a known weight."""
    pcs = await _uom_id(db, 'pcs')
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        uom_id=pcs,
        weight_value=Decimal(grams_per_bag),
        weight_uom_id=await _uom_id(db, 'g'),
    )
    db.add(template)
    await db.flush()
    set_template_nutrition(
        template, {'calories_kcal': kcal_per_100g, 'fat_g': 35.0, 'protein_g': 4.0}
    )
    db.add(
        Item(
            organization_id=org.id,
            storage_location_id=location.id,
            template_id=template.id,
            name=name,
            uom_id=pcs,
            quantity=Decimal('13'),
        )
    )
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return template


async def _recipe_with_one_line(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    name: str,
    quantity: str,
    uom_symbol: str | None,
) -> Recipe:
    """One serving, one unlinked line — the shape a hand-typed ingredient takes."""
    recipe = Recipe(
        organization_id=org.id, name=f'QA {name}', servings=1, created_by=user.id
    )
    db.add(recipe)
    await db.flush()
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            name=name,
            quantity=Decimal(quantity),
            uom_id=await _uom_id(db, uom_symbol) if uom_symbol else None,
            sort_order=0,
        )
    )
    await db.flush()
    await db.refresh(recipe, ['ingredients'])
    return recipe


async def test_a_unitless_salt_line_does_not_borrow_the_crisps_calories(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    db = real_async_db_session
    await _stock_bags(
        db,
        async_test_household,
        async_test_storage_location,
        name='Salted Potato Crisps',
        grams_per_bag='165',
        kcal_per_100g=536.0,
    )
    recipe = await _recipe_with_one_line(
        db,
        async_test_household,
        async_test_user,
        name='Salt',
        quantity='1',
        uom_symbol=None,
    )

    # The precondition the defect lived on: the matcher does reach the
    # crisps, and the shelf comparison refuses them.
    availability = await get_recipe_availability(
        db, recipe, async_test_household.id, recipe.servings
    )
    line = availability.ingredients[0]
    assert line.match_type == 'fuzzy'
    assert line.status == 'incomparable'

    result = await get_recipe_nutrition(
        db, recipe, async_test_household.id, recipe.servings
    )

    # One 165 g bag at 536 kcal/100 g is the 884.4 the recipe used to report.
    assert result['per_serving'].get('calories_kcal') != pytest.approx(884.4)
    assert result['total'] == {}
    assert result['ingredients'][0]['has_data'] is False
    assert result['missing_nutrition'] == ['Salt']
    assert result['coverage'] == 0.0


async def test_a_match_whose_measures_meet_still_lends_its_values(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    """The same kind of name match, counted in the unit the shelf counts in."""
    db = real_async_db_session
    await _stock_bags(
        db,
        async_test_household,
        async_test_storage_location,
        name='Salted Potato Crisps',
        grams_per_bag='165',
        kcal_per_100g=536.0,
    )
    recipe = await _recipe_with_one_line(
        db,
        async_test_household,
        async_test_user,
        name='Salted Potato Crisps',
        quantity='1',
        uom_symbol='pcs',
    )

    availability = await get_recipe_availability(
        db, recipe, async_test_household.id, recipe.servings
    )
    assert availability.ingredients[0].quantities_comparable is True

    result = await get_recipe_nutrition(
        db, recipe, async_test_household.id, recipe.servings
    )

    assert result['total']['calories_kcal'] == pytest.approx(884.4, abs=0.1)
    assert result['coverage'] == 1.0
