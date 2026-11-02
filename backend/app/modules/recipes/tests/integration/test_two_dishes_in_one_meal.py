"""A meal holds more than one dish, and the grid has always said so.

Every cell in the planner offers a "+" underneath the dish already in it and
a drag handle on each entry. Writing that second dish was a 500: the create
schema defaulted the position within the cell to 0, which is where the first
dish sits, so the insert hit
``uq_meal_plan_entries_plan_date_slot_order`` and left as an unhandled
``IntegrityError``. The screen said "Could not add recipe", which reads like a
hiccup, so the obvious thing to do was try again.

The defence against exactly this collision already existed one function
lower, in the move path. These tests hold both ends: a dish added without a
position goes after what is there, and the two paths agree about where that
is.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.recipes._meal_plan import add_entry_async, update_entry_async
from app.modules.recipes.models import MealPlan, MealPlanEntry, MealSlot, Recipe
from app.modules.recipes.schemas import (
    MealPlanEntryCreate,
    MealPlanEntrySchema,
    MealPlanEntryUpdate,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_TODAY = date.today()


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    organization = Organization(
        name='Sunday Dinner Org', enabled_modules=['core', 'recipes']
    )
    real_async_db_session.add(organization)
    await real_async_db_session.flush()
    return organization


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        org,
        email='sunday-dinner@example.com',
        role='admin',
    )


@pytest.fixture
async def plan(
    real_async_db_session: AsyncSession, org: Organization, user: User
) -> MealPlan:
    meal_plan = MealPlan(
        organization_id=org.id,
        name='This week',
        start_date=_TODAY,
        end_date=_TODAY + timedelta(days=6),
        enabled_slots=[MealSlot.LUNCH.value, MealSlot.DINNER.value],
        created_by=user.id,
    )
    real_async_db_session.add(meal_plan)
    await real_async_db_session.flush()
    return meal_plan


async def _recipe(db: AsyncSession, org: Organization, user: User, name: str) -> Recipe:
    recipe = Recipe(organization_id=org.id, name=name, servings=4, created_by=user.id)
    db.add(recipe)
    await db.flush()
    return recipe


async def _add(
    db: AsyncSession,
    plan: MealPlan,
    recipe: Recipe,
    org: Organization,
    *,
    slot: MealSlot = MealSlot.LUNCH,
    when: date | None = None,
    order: int | None = None,
) -> MealPlanEntrySchema:
    return await add_entry_async(
        db,
        plan.id,
        MealPlanEntryCreate(
            date=when or _TODAY,
            slot=slot,
            recipe_id=recipe.id,
            order=order,
        ),
        org.id,
    )


async def _orders_in_cell(
    db: AsyncSession, plan: MealPlan, slot: MealSlot = MealSlot.LUNCH
) -> list[int]:
    rows = await db.scalars(
        select(MealPlanEntry.order)
        .where(
            MealPlanEntry.meal_plan_id == plan.id,
            MealPlanEntry.date == _TODAY,
            MealPlanEntry.slot == slot,
        )
        .order_by(MealPlanEntry.order)
    )
    return list(rows)


async def test_a_soup_and_a_main_course_share_one_lunch(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    plan: MealPlan,
) -> None:
    db = real_async_db_session
    soup = await _recipe(db, org, user, 'Tomato soup')
    main = await _recipe(db, org, user, 'Roast chicken')

    first = await _add(db, plan, soup, org)
    second = await _add(db, plan, main, org)

    assert first.order == 0
    assert second.order == 1
    assert await _orders_in_cell(db, plan) == [0, 1]


async def test_a_third_dish_goes_after_the_other_two(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    plan: MealPlan,
) -> None:
    """Appending is not a special case of "the cell holds exactly one"."""
    db = real_async_db_session
    for name in ('Tomato soup', 'Roast chicken', 'Apple pie'):
        await _add(db, plan, await _recipe(db, org, user, name), org)

    assert await _orders_in_cell(db, plan) == [0, 1, 2]


async def test_each_meal_counts_its_own_positions(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    plan: MealPlan,
) -> None:
    """The position is per (date, slot) — dinner does not continue lunch."""
    db = real_async_db_session
    soup = await _recipe(db, org, user, 'Tomato soup')
    main = await _recipe(db, org, user, 'Roast chicken')

    await _add(db, plan, soup, org, slot=MealSlot.LUNCH)
    dinner = await _add(db, plan, main, org, slot=MealSlot.DINNER)

    assert dinner.order == 0
    assert await _orders_in_cell(db, plan, MealSlot.DINNER) == [0]


async def test_an_explicit_position_is_still_honoured(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    plan: MealPlan,
) -> None:
    """Omitting the position asks for the end; naming one still names one."""
    db = real_async_db_session
    soup = await _recipe(db, org, user, 'Tomato soup')

    entry = await _add(db, plan, soup, org, order=7)

    assert entry.order == 7


async def test_a_dish_moved_into_an_occupied_meal_lands_after_it(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    plan: MealPlan,
) -> None:
    """Adding and moving have to agree about where the end of a cell is."""
    db = real_async_db_session
    soup = await _recipe(db, org, user, 'Tomato soup')
    main = await _recipe(db, org, user, 'Roast chicken')

    await _add(db, plan, soup, org, slot=MealSlot.LUNCH)
    dinner_entry = await _add(db, plan, main, org, slot=MealSlot.DINNER)

    moved = await update_entry_async(
        db,
        plan.id,
        dinner_entry.id,
        MealPlanEntryUpdate(slot=MealSlot.LUNCH),
        org.id,
    )

    assert moved.slot == MealSlot.LUNCH
    assert moved.order == 1
    assert await _orders_in_cell(db, plan) == [0, 1]
