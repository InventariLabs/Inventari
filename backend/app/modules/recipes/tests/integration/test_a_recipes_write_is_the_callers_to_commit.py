"""A recipes service write belongs to the caller's transaction.

The request-scoped session commits once, when the endpoint returns. A service
that commits on its own slices the request in two: whatever fails after that
point leaves the first half in the database. Each case below runs one write,
then plays the part of a later failure — the caller rolls back — and asks the
database what is left. Nothing may be.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.recipes._collections import create_collection_async
from app.modules.recipes._meal_plan import create_meal_plan_async
from app.modules.recipes.models import (
    MealPlan,
    RecipeCollection,
    RecipeTagConfig,
    UnitConversion,
)
from app.modules.recipes.schemas import MealPlanCreate, RecipeCollectionCreate
from app.modules.recipes.tag_service import upsert_tag_color
from app.modules.recipes.unit_conversion_service import create_conversion

_Write = Callable[[AsyncSession, Organization, User], Awaitable[object]]


async def _a_collection(db: AsyncSession, org: Organization, user: User) -> object:
    return await create_collection_async(
        db, org.id, user.id, RecipeCollectionCreate(name='Weeknights')
    )


async def _a_tag_colour(db: AsyncSession, org: Organization, user: User) -> object:
    return await upsert_tag_color(db, 'vegan', '#33aa55', org.id)


async def _a_meal_plan(db: AsyncSession, org: Organization, user: User) -> object:
    today = date.today()
    return await create_meal_plan_async(
        db,
        MealPlanCreate(start_date=today, end_date=today + timedelta(days=6)),
        org.id,
        user.id,
    )


async def _a_conversion(db: AsyncSession, org: Organization, user: User) -> object:
    return await create_conversion(
        db,
        org.id,
        'flour',
        'Flour',
        'cup',
        Decimal('120'),
        'g',
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ('write', 'model'),
    [
        (_a_collection, RecipeCollection),
        (_a_tag_colour, RecipeTagConfig),
        (_a_meal_plan, MealPlan),
        (_a_conversion, UnitConversion),
    ],
    ids=['collection', 'tag_colour', 'meal_plan', 'conversion'],
)
async def test_a_failure_after_the_write_leaves_no_partial_row(
    real_async_db_session: AsyncSession, write: _Write, model: type
) -> None:
    db = real_async_db_session
    org = Organization(name='Caller Owns Org', enabled_modules=['core', 'recipes'])
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email='caller-owns@example.com', role='admin'
    )

    rows = select(func.count()).select_from(model)
    before = await db.scalar(rows) or 0

    await write(db, org, user)
    assert await db.scalar(rows) == before + 1

    # The caller's unit of work fails after the service returned.
    await db.rollback()

    assert await db.scalar(rows) == before
