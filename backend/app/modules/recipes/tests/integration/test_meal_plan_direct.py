"""Direct integration tests for ``_meal_plan``.

The existing meal-plan tests drive these functions through the FastAPI
``TestClient``, which runs the async app in a separate blocking-portal
thread. Coverage's tracer does not reliably record statements after the first
``await`` inside that worker thread, so those endpoint tests leave most of
this module around 27%. These tests call the service functions directly on a
real ``AsyncSession`` so the lines are attributed correctly.

Meal planning is the core of the recipes module. The scenarios here cover
plan CRUD, meal-slot assignment, entry moves, bulk replacement, week copying,
and the "cook now" picking hand-off, including the error paths.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException, NotFoundException
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.recipes._meal_plan import (
    add_entry_async,
    bulk_save_entries_async,
    copy_plan_to_week_async,
    create_meal_plan_async,
    delete_entry_async,
    delete_meal_plan_async,
    get_meal_plan_async,
    list_meal_plans_async,
    update_entry_async,
    update_meal_plan_async,
)
from app.modules.recipes.models import MealPlan, MealPlanEntry, MealSlot, Recipe
from app.modules.recipes.schemas import (
    BulkEntriesSave,
    CopyPlanRequest,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanEntryUpdate,
    MealPlanUpdate,
)

_TODAY = date.today()


def _detail(exc: AppException) -> dict[str, Any]:
    """Return the structured ``detail`` payload carried by app exceptions."""
    return cast(dict[str, Any], exc.detail)


@pytest.fixture
async def meal_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Meal Plan Ops Org', enabled_modules=['core', 'recipes'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def meal_user(
    real_async_db_session: AsyncSession, meal_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        meal_org,
        email='meal-plan-ops@example.com',
        role='admin',
    )


async def _recipe(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    name: str = 'Test Recipe',
    servings: int = 1,
) -> Recipe:
    recipe = Recipe(
        organization_id=org.id,
        name=name,
        servings=servings,
        created_by=user.id,
    )
    db.add(recipe)
    await db.flush()
    return recipe


async def _plan(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    start: date,
    end: date,
    slots: list[MealSlot],
    name: str | None = None,
    default_servings: int | None = None,
    notes: str | None = None,
) -> MealPlan:
    plan = MealPlan(
        organization_id=org.id,
        name=name,
        start_date=start,
        end_date=end,
        enabled_slots=[slot.value for slot in slots],
        default_servings=default_servings,
        notes=notes,
        created_by=user.id,
    )
    db.add(plan)
    await db.flush()
    return plan


async def _entry(
    db: AsyncSession,
    plan: MealPlan,
    recipe: Recipe,
    *,
    on: date,
    slot: MealSlot,
    order: int = 0,
    servings: int | None = None,
    notes: str | None = None,
) -> MealPlanEntry:
    entry = MealPlanEntry(
        meal_plan_id=plan.id,
        date=on,
        slot=slot,
        recipe_id=recipe.id,
        servings=servings,
        notes=notes,
        order=order,
    )
    db.add(entry)
    await db.flush()
    return entry


async def _plan_with_entry(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    start: date,
    end: date,
    slots: list[MealSlot],
    entry_date: date,
    entry_slot: MealSlot,
    recipe_name: str = 'Test Recipe',
    order: int = 0,
    servings: int | None = None,
) -> tuple[MealPlan, MealPlanEntry, Recipe]:
    plan = await _plan(db, org, user, start=start, end=end, slots=slots)
    recipe = await _recipe(db, org, user, name=recipe_name)
    entry = await _entry(
        db,
        plan,
        recipe,
        on=entry_date,
        slot=entry_slot,
        order=order,
        servings=servings,
    )
    return plan, entry, recipe


async def _get_plan_row(db: AsyncSession, plan_id: UUID) -> MealPlan | None:
    result = await db.execute(select(MealPlan).where(MealPlan.id == plan_id))
    return cast(MealPlan | None, result.scalar_one_or_none())


async def _get_entry_rows(db: AsyncSession, plan_id: UUID) -> list[MealPlanEntry]:
    result = await db.execute(
        select(MealPlanEntry).where(MealPlanEntry.meal_plan_id == plan_id)
    )
    return cast(list[MealPlanEntry], list(result.scalars().all()))


@pytest.mark.integration
class TestCreateMealPlan:
    @pytest.mark.asyncio
    async def test_create_plan_with_explicit_name_success(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        schema = await create_meal_plan_async(
            real_async_db_session,
            MealPlanCreate(
                name='Test Week',
                start_date=_TODAY,
                end_date=_TODAY + timedelta(days=6),
                enabled_slots=[MealSlot.LUNCH, MealSlot.DINNER],
                default_servings=2,
            ),
            meal_org.id,
            meal_user.id,
        )

        assert schema.name == 'Test Week'
        assert schema.start_date == _TODAY
        assert schema.end_date == _TODAY + timedelta(days=6)
        assert schema.enabled_slots == [MealSlot.LUNCH, MealSlot.DINNER]
        assert schema.default_servings == 2
        assert schema.entries == []

    @pytest.mark.asyncio
    async def test_create_plan_auto_generates_name(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        schema = await create_meal_plan_async(
            real_async_db_session,
            MealPlanCreate(
                name=None,
                start_date=_TODAY,
                end_date=_TODAY + timedelta(days=1),
                enabled_slots=[MealSlot.LUNCH],
            ),
            meal_org.id,
            meal_user.id,
        )

        assert schema.name is not None
        assert 'Plan' in schema.name

    @pytest.mark.asyncio
    async def test_create_plan_end_before_start_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        with pytest.raises(
            ValueError, match='The end date must not be before the start date'
        ):
            await create_meal_plan_async(
                real_async_db_session,
                MealPlanCreate(
                    start_date=_TODAY,
                    end_date=_TODAY - timedelta(days=1),
                    enabled_slots=[MealSlot.LUNCH],
                ),
                meal_org.id,
                meal_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_plan_exceeding_14_days_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        with pytest.raises(ValueError, match='Plan cannot exceed 14 days'):
            await create_meal_plan_async(
                real_async_db_session,
                MealPlanCreate(
                    start_date=_TODAY,
                    end_date=_TODAY + timedelta(days=15),
                    enabled_slots=[MealSlot.LUNCH],
                ),
                meal_org.id,
                meal_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_plan_empty_slots_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        with pytest.raises(ValueError, match='Enable at least one meal slot'):
            await create_meal_plan_async(
                real_async_db_session,
                MealPlanCreate(
                    start_date=_TODAY,
                    end_date=_TODAY + timedelta(days=1),
                    enabled_slots=[],
                ),
                meal_org.id,
                meal_user.id,
            )


@pytest.mark.integration
class TestGetMealPlan:
    @pytest.mark.asyncio
    async def test_get_plan_returns_schema(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            name='Week',
        )

        schema = await get_meal_plan_async(real_async_db_session, plan.id, meal_org.id)

        assert schema is not None
        assert schema.id == plan.id
        assert schema.name == 'Week'

    @pytest.mark.asyncio
    async def test_get_plan_missing_returns_none(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
    ) -> None:
        assert (
            await get_meal_plan_async(real_async_db_session, uuid.uuid4(), meal_org.id)
            is None
        )


@pytest.mark.integration
class TestListMealPlans:
    @pytest.mark.asyncio
    async def test_list_plans_empty_returns_empty_list(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
    ) -> None:
        assert await list_meal_plans_async(real_async_db_session, meal_org.id) == []

    @pytest.mark.asyncio
    async def test_list_plans_returns_entry_counts_and_default_servings(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        recipe = await _recipe(real_async_db_session, meal_org, meal_user)
        plan_a = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            default_servings=None,
        )
        await _entry(
            real_async_db_session,
            plan_a,
            recipe,
            on=_TODAY,
            slot=MealSlot.LUNCH,
        )
        await _entry(
            real_async_db_session,
            plan_a,
            recipe,
            on=_TODAY + timedelta(days=1),
            slot=MealSlot.LUNCH,
        )
        await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY + timedelta(days=7),
            end=_TODAY + timedelta(days=13),
            slots=[MealSlot.LUNCH],
            default_servings=3,
        )

        rows = await list_meal_plans_async(real_async_db_session, meal_org.id)

        assert len(rows) == 2
        by_id = {row['id']: row for row in rows}
        assert by_id[plan_a.id]['entry_count'] == 2
        # A plan that states no default reports none — the list used to
        # substitute 2, which reads as a setting somebody chose.
        assert by_id[plan_a.id]['default_servings'] is None
        assert by_id[plan_a.id]['enabled_slots'] == [MealSlot.LUNCH]

    @pytest.mark.asyncio
    async def test_list_plans_filters_by_date_overlap(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        early = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )
        late = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY + timedelta(days=14),
            end=_TODAY + timedelta(days=20),
            slots=[MealSlot.LUNCH],
        )

        from_mid = await list_meal_plans_async(
            real_async_db_session,
            meal_org.id,
            start_date=_TODAY + timedelta(days=10),
        )
        assert [row['id'] for row in from_mid] == [late.id]

        until_next_week = await list_meal_plans_async(
            real_async_db_session,
            meal_org.id,
            end_date=_TODAY + timedelta(days=7),
        )
        assert [row['id'] for row in until_next_week] == [early.id]

    @pytest.mark.asyncio
    async def test_list_plans_paginates_by_start_date_desc(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        first = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY,
            slots=[MealSlot.LUNCH],
        )
        second = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY + timedelta(days=1),
            end=_TODAY + timedelta(days=1),
            slots=[MealSlot.LUNCH],
        )
        third = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY + timedelta(days=2),
            end=_TODAY + timedelta(days=2),
            slots=[MealSlot.LUNCH],
        )

        all_rows = await list_meal_plans_async(real_async_db_session, meal_org.id)
        assert [row['id'] for row in all_rows] == [third.id, second.id, first.id]

        page = await list_meal_plans_async(
            real_async_db_session, meal_org.id, skip=1, limit=1
        )
        assert [row['id'] for row in page] == [second.id]


@pytest.mark.integration
class TestUpdateMealPlan:
    @pytest.mark.asyncio
    async def test_update_plan_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
    ) -> None:
        with pytest.raises(NotFoundException) as exc_info:
            await update_meal_plan_async(
                real_async_db_session,
                uuid.uuid4(),
                MealPlanUpdate(name='Nope'),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'MEAL_PLAN_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_update_name_servings_notes_and_dates(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        new_start = _TODAY + timedelta(days=1)
        new_end = _TODAY + timedelta(days=5)
        schema = await update_meal_plan_async(
            real_async_db_session,
            plan.id,
            MealPlanUpdate(
                name='Updated',
                default_servings=4,
                notes='Dinner week',
                start_date=new_start,
                end_date=new_end,
            ),
            meal_org.id,
        )

        assert schema.name == 'Updated'
        assert schema.default_servings == 4
        assert schema.notes == 'Dinner week'
        assert schema.start_date == new_start
        assert schema.end_date == new_end

    @pytest.mark.asyncio
    async def test_update_enabled_slots_empty_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(ValueError, match='Enable at least one meal slot'):
            await update_meal_plan_async(
                real_async_db_session,
                plan.id,
                MealPlanUpdate(enabled_slots=[]),
                meal_org.id,
            )

    @pytest.mark.asyncio
    async def test_update_disabling_empty_slot_succeeds(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH, MealSlot.DINNER, MealSlot.SNACK],
        )

        schema = await update_meal_plan_async(
            real_async_db_session,
            plan.id,
            MealPlanUpdate(enabled_slots=[MealSlot.LUNCH, MealSlot.DINNER]),
            meal_org.id,
        )

        assert schema.enabled_slots == [MealSlot.LUNCH, MealSlot.DINNER]

    @pytest.mark.asyncio
    async def test_update_disabling_slot_with_entries_conflicts(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, _, recipe = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH, MealSlot.DINNER],
            entry_date=_TODAY,
            entry_slot=MealSlot.DINNER,
        )
        await _entry(
            real_async_db_session,
            plan,
            recipe,
            on=_TODAY + timedelta(days=1),
            slot=MealSlot.DINNER,
        )

        with pytest.raises(ConflictException) as exc_info:
            await update_meal_plan_async(
                real_async_db_session,
                plan.id,
                MealPlanUpdate(enabled_slots=[MealSlot.LUNCH]),
                meal_org.id,
            )

        assert _detail(exc_info.value)['code'] == 'MEAL_PLAN_SLOT_CONFLICT'
        assert _detail(exc_info.value)['conflicts'] == [{'slot': 'DINNER', 'count': 2}]

    @pytest.mark.asyncio
    async def test_update_disabling_slot_remove_conflicting_entries(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, _, recipe = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH, MealSlot.DINNER],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )
        await _entry(
            real_async_db_session,
            plan,
            recipe,
            on=_TODAY,
            slot=MealSlot.DINNER,
        )
        await _entry(
            real_async_db_session,
            plan,
            recipe,
            on=_TODAY + timedelta(days=1),
            slot=MealSlot.DINNER,
        )

        schema = await update_meal_plan_async(
            real_async_db_session,
            plan.id,
            MealPlanUpdate(
                enabled_slots=[MealSlot.LUNCH],
                remove_conflicting_entries=True,
            ),
            meal_org.id,
        )

        assert schema.enabled_slots == [MealSlot.LUNCH]
        assert len(schema.entries) == 1
        assert schema.entries[0].slot == MealSlot.LUNCH

    @pytest.mark.asyncio
    async def test_update_date_range_end_before_start_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(
            ValueError, match='The end date must not be before the start date'
        ):
            await update_meal_plan_async(
                real_async_db_session,
                plan.id,
                MealPlanUpdate(
                    start_date=_TODAY + timedelta(days=5),
                    end_date=_TODAY,
                ),
                meal_org.id,
            )

    @pytest.mark.asyncio
    async def test_update_date_range_too_long_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(ValueError, match='Plan cannot exceed 14 days'):
            await update_meal_plan_async(
                real_async_db_session,
                plan.id,
                MealPlanUpdate(
                    start_date=_TODAY,
                    end_date=_TODAY + timedelta(days=15),
                ),
                meal_org.id,
            )

    @pytest.mark.asyncio
    async def test_update_date_range_conflicts_with_existing_entries(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, _, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        with pytest.raises(ConflictException) as exc_info:
            await update_meal_plan_async(
                real_async_db_session,
                plan.id,
                MealPlanUpdate(start_date=_TODAY + timedelta(days=1)),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'MEAL_PLAN_DATE_CONFLICT'


@pytest.mark.integration
class TestDeleteMealPlan:
    @pytest.mark.asyncio
    async def test_delete_plan_success(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        assert await delete_meal_plan_async(
            real_async_db_session, plan.id, meal_org.id, meal_user.id
        )
        assert await _get_plan_row(real_async_db_session, plan.id) is None

    @pytest.mark.asyncio
    async def test_delete_plan_missing_returns_false(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        assert not await delete_meal_plan_async(
            real_async_db_session, uuid.uuid4(), meal_org.id, meal_user.id
        )


@pytest.mark.integration
class TestAddEntry:
    @pytest.mark.asyncio
    async def test_add_entry_success(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )
        recipe = await _recipe(real_async_db_session, meal_org, meal_user)

        entry = await add_entry_async(
            real_async_db_session,
            plan.id,
            MealPlanEntryCreate(
                date=_TODAY,
                slot=MealSlot.LUNCH,
                recipe_id=recipe.id,
                servings=3,
                notes='Extra sauce',
                order=0,
            ),
            meal_org.id,
        )

        assert entry.recipe_id == recipe.id
        assert entry.recipe_name == recipe.name
        assert entry.slot == MealSlot.LUNCH
        assert entry.servings == 3
        assert entry.notes == 'Extra sauce'

    @pytest.mark.asyncio
    async def test_add_entry_plan_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        recipe = await _recipe(real_async_db_session, meal_org, meal_user)
        with pytest.raises(NotFoundException) as exc_info:
            await add_entry_async(
                real_async_db_session,
                uuid.uuid4(),
                MealPlanEntryCreate(
                    date=_TODAY,
                    slot=MealSlot.LUNCH,
                    recipe_id=recipe.id,
                ),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'MEAL_PLAN_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_add_entry_out_of_range_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )
        recipe = await _recipe(real_async_db_session, meal_org, meal_user)

        with pytest.raises(ConflictException) as exc_info:
            await add_entry_async(
                real_async_db_session,
                plan.id,
                MealPlanEntryCreate(
                    date=_TODAY + timedelta(days=30),
                    slot=MealSlot.LUNCH,
                    recipe_id=recipe.id,
                ),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'ENTRY_DATE_OUT_OF_RANGE'

    @pytest.mark.asyncio
    async def test_add_entry_disabled_slot_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )
        recipe = await _recipe(real_async_db_session, meal_org, meal_user)

        with pytest.raises(ConflictException) as exc_info:
            await add_entry_async(
                real_async_db_session,
                plan.id,
                MealPlanEntryCreate(
                    date=_TODAY,
                    slot=MealSlot.DINNER,
                    recipe_id=recipe.id,
                ),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'SLOT_NOT_ENABLED'

    @pytest.mark.asyncio
    async def test_add_entry_recipe_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(NotFoundException) as exc_info:
            await add_entry_async(
                real_async_db_session,
                plan.id,
                MealPlanEntryCreate(
                    date=_TODAY,
                    slot=MealSlot.LUNCH,
                    recipe_id=uuid.uuid4(),
                ),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'RECIPE_NOT_FOUND'


@pytest.mark.integration
class TestUpdateEntry:
    @pytest.mark.asyncio
    async def test_update_entry_servings_notes_and_order(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        updated = await update_entry_async(
            real_async_db_session,
            plan.id,
            entry.id,
            MealPlanEntryUpdate(servings=4, notes='Less salt', order=2),
            meal_org.id,
        )

        assert updated.servings == 4
        assert updated.notes == 'Less salt'
        assert updated.order == 2
        assert updated.date == _TODAY
        assert updated.slot == MealSlot.LUNCH

    @pytest.mark.asyncio
    async def test_update_entry_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(NotFoundException) as exc_info:
            await update_entry_async(
                real_async_db_session,
                plan.id,
                uuid.uuid4(),
                MealPlanEntryUpdate(notes='Nope'),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'MEAL_PLAN_ENTRY_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_update_entry_recipe_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        with pytest.raises(NotFoundException) as exc_info:
            await update_entry_async(
                real_async_db_session,
                plan.id,
                entry.id,
                MealPlanEntryUpdate(recipe_id=uuid.uuid4()),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'RECIPE_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_update_entry_changes_recipe(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
            recipe_name='Original',
        )
        replacement = await _recipe(
            real_async_db_session, meal_org, meal_user, name='Replacement'
        )

        updated = await update_entry_async(
            real_async_db_session,
            plan.id,
            entry.id,
            MealPlanEntryUpdate(recipe_id=replacement.id),
            meal_org.id,
        )

        assert updated.recipe_id == replacement.id
        # fix: the re-fetch after commit must see the fresh
        # relationship, not the pre-update identity-map object.
        assert updated.recipe_name == 'Replacement'

    @pytest.mark.asyncio
    async def test_update_entry_move_to_empty_cell(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH, MealSlot.DINNER],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        tomorrow = _TODAY + timedelta(days=1)
        updated = await update_entry_async(
            real_async_db_session,
            plan.id,
            entry.id,
            MealPlanEntryUpdate(date=tomorrow, slot=MealSlot.DINNER),
            meal_org.id,
        )

        assert updated.date == tomorrow
        assert updated.slot == MealSlot.DINNER
        assert updated.order == 0

    @pytest.mark.asyncio
    async def test_update_entry_same_cell_keeps_order(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        updated = await update_entry_async(
            real_async_db_session,
            plan.id,
            entry.id,
            MealPlanEntryUpdate(date=_TODAY, slot=MealSlot.LUNCH, notes='Stayed'),
            meal_org.id,
        )

        assert updated.date == _TODAY
        assert updated.slot == MealSlot.LUNCH
        assert updated.order == 0
        assert updated.notes == 'Stayed'

    @pytest.mark.asyncio
    async def test_update_entry_move_collision_bumps_order(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, moving, recipe = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )
        tomorrow = _TODAY + timedelta(days=1)
        await _entry(
            real_async_db_session,
            plan,
            recipe,
            on=tomorrow,
            slot=MealSlot.LUNCH,
            order=0,
        )

        updated = await update_entry_async(
            real_async_db_session,
            plan.id,
            moving.id,
            MealPlanEntryUpdate(date=tomorrow, slot=MealSlot.LUNCH),
            meal_org.id,
        )

        assert updated.date == tomorrow
        assert updated.slot == MealSlot.LUNCH
        assert updated.order == 1

    @pytest.mark.asyncio
    async def test_update_entry_move_out_of_range_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        with pytest.raises(ConflictException) as exc_info:
            await update_entry_async(
                real_async_db_session,
                plan.id,
                entry.id,
                MealPlanEntryUpdate(date=_TODAY + timedelta(days=30)),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'ENTRY_DATE_OUT_OF_RANGE'

    @pytest.mark.asyncio
    async def test_update_entry_move_disabled_slot_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        with pytest.raises(ConflictException) as exc_info:
            await update_entry_async(
                real_async_db_session,
                plan.id,
                entry.id,
                MealPlanEntryUpdate(slot=MealSlot.DINNER),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'SLOT_NOT_ENABLED'


@pytest.mark.integration
class TestDeleteEntry:
    @pytest.mark.asyncio
    async def test_delete_entry_success(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, entry, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        assert await delete_entry_async(
            real_async_db_session, plan.id, entry.id, meal_org.id
        )
        schema = await get_meal_plan_async(real_async_db_session, plan.id, meal_org.id)
        assert schema is not None
        assert schema.entries == []

    @pytest.mark.asyncio
    async def test_delete_entry_missing_returns_false(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        assert not await delete_entry_async(
            real_async_db_session, plan.id, uuid.uuid4(), meal_org.id
        )


@pytest.mark.integration
class TestBulkSaveEntries:
    @pytest.mark.asyncio
    async def test_bulk_save_replaces_existing_entries(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, _, old_recipe = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH, MealSlot.DINNER],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
            recipe_name='Old',
        )
        new_recipe = await _recipe(
            real_async_db_session, meal_org, meal_user, name='New'
        )

        schema = await bulk_save_entries_async(
            real_async_db_session,
            plan.id,
            BulkEntriesSave(
                entries=[
                    MealPlanEntryCreate(
                        date=_TODAY,
                        slot=MealSlot.LUNCH,
                        recipe_id=new_recipe.id,
                        order=0,
                    ),
                    MealPlanEntryCreate(
                        date=_TODAY,
                        slot=MealSlot.DINNER,
                        recipe_id=new_recipe.id,
                        order=1,
                    ),
                ]
            ),
            meal_org.id,
        )

        # fix: the re-fetch after commit must see the fresh entry
        # collection, not the pre-replacement identity-map rows.
        assert len(schema.entries) == 2
        assert {e.recipe_name for e in schema.entries} == {'New'}

        db_entries = await _get_entry_rows(real_async_db_session, plan.id)
        assert len(db_entries) == 2
        assert {entry.recipe_id for entry in db_entries} == {new_recipe.id}
        assert {entry.slot for entry in db_entries} == {
            MealSlot.LUNCH,
            MealSlot.DINNER,
        }
        assert old_recipe.id != new_recipe.id

    @pytest.mark.asyncio
    async def test_bulk_save_empty_clears_entries(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, _, _ = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )

        schema = await bulk_save_entries_async(
            real_async_db_session,
            plan.id,
            BulkEntriesSave(entries=[]),
            meal_org.id,
        )

        # fix: the returned schema must reflect the cleared plan,
        # not the pre-deletion identity-map entry collection.
        assert schema.entries == []
        assert await _get_entry_rows(real_async_db_session, plan.id) == []

    @pytest.mark.asyncio
    async def test_bulk_save_plan_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        recipe = await _recipe(real_async_db_session, meal_org, meal_user)
        with pytest.raises(NotFoundException):
            await bulk_save_entries_async(
                real_async_db_session,
                uuid.uuid4(),
                BulkEntriesSave(
                    entries=[
                        MealPlanEntryCreate(
                            date=_TODAY,
                            slot=MealSlot.LUNCH,
                            recipe_id=recipe.id,
                        )
                    ]
                ),
                meal_org.id,
            )

    @pytest.mark.asyncio
    async def test_bulk_save_invalid_date_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )
        recipe = await _recipe(real_async_db_session, meal_org, meal_user)

        with pytest.raises(ConflictException) as exc_info:
            await bulk_save_entries_async(
                real_async_db_session,
                plan.id,
                BulkEntriesSave(
                    entries=[
                        MealPlanEntryCreate(
                            date=_TODAY + timedelta(days=30),
                            slot=MealSlot.LUNCH,
                            recipe_id=recipe.id,
                        )
                    ]
                ),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'ENTRY_DATE_OUT_OF_RANGE'

    @pytest.mark.asyncio
    async def test_bulk_save_recipe_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(NotFoundException) as exc_info:
            await bulk_save_entries_async(
                real_async_db_session,
                plan.id,
                BulkEntriesSave(
                    entries=[
                        MealPlanEntryCreate(
                            date=_TODAY,
                            slot=MealSlot.LUNCH,
                            recipe_id=uuid.uuid4(),
                        )
                    ]
                ),
                meal_org.id,
            )
        assert _detail(exc_info.value)['code'] == 'RECIPE_NOT_FOUND'


@pytest.mark.integration
class TestCopyPlanToWeek:
    @pytest.mark.asyncio
    async def test_copy_plan_success_shifts_entries(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, _, recipe = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH, MealSlot.DINNER],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )
        await _entry(
            real_async_db_session,
            plan,
            recipe,
            on=_TODAY + timedelta(days=1),
            slot=MealSlot.DINNER,
        )

        target_start = _TODAY + timedelta(days=7)
        target_end = _TODAY + timedelta(days=13)
        schema, copied, skipped = await copy_plan_to_week_async(
            real_async_db_session,
            plan.id,
            CopyPlanRequest(start_date=target_start, end_date=target_end),
            meal_org.id,
            meal_user.id,
        )

        assert copied == 2
        assert skipped == 0
        assert schema.id != plan.id
        assert schema.start_date == target_start
        assert schema.end_date == target_end
        assert schema.enabled_slots == [MealSlot.LUNCH, MealSlot.DINNER]
        entry_keys = {(entry.date, entry.slot) for entry in schema.entries}
        assert entry_keys == {
            (target_start, MealSlot.LUNCH),
            (target_start + timedelta(days=1), MealSlot.DINNER),
        }

    @pytest.mark.asyncio
    async def test_copy_plan_skips_out_of_range_entries(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan, _, recipe = await _plan_with_entry(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
            entry_date=_TODAY,
            entry_slot=MealSlot.LUNCH,
        )
        await _entry(
            real_async_db_session,
            plan,
            recipe,
            on=_TODAY + timedelta(days=6),
            slot=MealSlot.LUNCH,
        )

        target_start = _TODAY + timedelta(days=7)
        schema, copied, skipped = await copy_plan_to_week_async(
            real_async_db_session,
            plan.id,
            CopyPlanRequest(start_date=target_start, end_date=target_start),
            meal_org.id,
            meal_user.id,
        )

        assert copied == 1
        assert skipped == 1
        assert [entry.date for entry in schema.entries] == [target_start]

    @pytest.mark.asyncio
    async def test_copy_plan_empty_source(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        target_start = _TODAY + timedelta(days=7)
        schema, copied, skipped = await copy_plan_to_week_async(
            real_async_db_session,
            plan.id,
            CopyPlanRequest(start_date=target_start, end_date=target_start),
            meal_org.id,
            meal_user.id,
        )

        assert copied == 0
        assert skipped == 0
        assert schema.entries == []

    @pytest.mark.asyncio
    async def test_copy_plan_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        with pytest.raises(NotFoundException):
            await copy_plan_to_week_async(
                real_async_db_session,
                uuid.uuid4(),
                CopyPlanRequest(start_date=_TODAY, end_date=_TODAY),
                meal_org.id,
                meal_user.id,
            )

    @pytest.mark.asyncio
    async def test_copy_plan_end_before_start_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(
            ValueError, match='The end date must not be before the start date'
        ):
            await copy_plan_to_week_async(
                real_async_db_session,
                plan.id,
                CopyPlanRequest(
                    start_date=_TODAY + timedelta(days=1),
                    end_date=_TODAY,
                ),
                meal_org.id,
                meal_user.id,
            )

    @pytest.mark.asyncio
    async def test_copy_plan_too_long_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(ValueError, match='Plan cannot exceed 14 days'):
            await copy_plan_to_week_async(
                real_async_db_session,
                plan.id,
                CopyPlanRequest(
                    start_date=_TODAY,
                    end_date=_TODAY + timedelta(days=15),
                ),
                meal_org.id,
                meal_user.id,
            )

    @pytest.mark.asyncio
    async def test_copy_plan_past_start_raises(
        self,
        real_async_db_session: AsyncSession,
        meal_org: Organization,
        meal_user: User,
    ) -> None:
        plan = await _plan(
            real_async_db_session,
            meal_org,
            meal_user,
            start=_TODAY,
            end=_TODAY + timedelta(days=6),
            slots=[MealSlot.LUNCH],
        )

        with pytest.raises(
            ValueError, match='Target start date must not be in the past'
        ):
            await copy_plan_to_week_async(
                real_async_db_session,
                plan.id,
                CopyPlanRequest(
                    start_date=_TODAY - timedelta(days=1),
                    end_date=_TODAY,
                ),
                meal_org.id,
                meal_user.id,
            )
