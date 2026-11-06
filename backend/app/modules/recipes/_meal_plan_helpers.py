"""Shared helpers for meal plan services."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.i18n.service import get_current_lang, get_error_message

from .models import MealPlan, MealPlanEntry, MealSlot, Recipe

#: A plan covers at most this many calendar days, first and last included.
_MAX_PLAN_DAYS = 14


def _plan_is_too_long(start: date, end: date) -> bool:
    """Whether a plan from *start* to *end* spans more than ``_MAX_PLAN_DAYS`` days.

    Both ends count: ``end - start`` is 13 days for a plan of fourteen.
    """
    return (end - start).days >= _MAX_PLAN_DAYS


def _get_effective_servings(
    entry: MealPlanEntry, plan: MealPlan, recipe: Recipe | None = None
) -> int:
    """How many servings this entry stands for.

    The entry decides; failing that the plan; failing that the recipe itself.
    The constant is the last resort and it used to be the second one, so a
    recipe written for one serving landed in a plan as two, and the shopping
    list asked for twice the ingredients nobody had agreed to.
    """
    if entry.servings:
        return entry.servings
    if plan.default_servings:
        return plan.default_servings
    # Only a recipe already in hand: `entry.recipe` is a lazy relationship and
    # touching it in an async session raises. Callers that hold the recipe
    # pass it; callers that loaded it eagerly get it from the identity map.
    source = recipe if recipe is not None else entry.__dict__.get('recipe')
    if source is not None and source.servings:
        return int(source.servings)
    return 2


def listed_meals_of(plan: MealPlan) -> list[list[Any]]:
    """The meals a shopping list made from this plan now is made from.

    Each meal as its recipe and the servings it stands for — what the list's
    quantities depend on; the day it is planned for is not. The servings are
    the effective ones the list is scaled by, not the entry's own field: an
    entry that states none follows the plan's default, and raising that
    default asks for more than the list was made for.
    """
    return [
        [str(entry.recipe_id), _get_effective_servings(entry, plan)]
        for entry in plan.entries
    ]


def _servings_by_recipe(meals: list[list[Any]]) -> Counter[str]:
    servings: Counter[str] = Counter()
    for recipe_id, count in meals:
        servings[str(recipe_id)] += int(count)
    return servings


def meals_not_on_the_list(plan: MealPlan) -> bool:
    """Whether the plan asks for more of a dish than its shopping list was made for.

    Asked of the meals the plan holds now against the ones the list was last
    generated from, so taking an added meal off again answers no. A mark set
    when a meal was planned stayed set after that meal was gone, and the plan
    screen went on saying a meal was missing from a list that carried every
    meal left. A plan with no list has nothing to be missing from. A plan
    listed before the meals were kept cannot say what its list carries, so it
    does not vouch for it: the screen offers the refresh, and the refresh
    records the meals.

    The list scales each recipe by the servings planned for it, so the
    comparison is each recipe's servings in total, not each meal on its own:
    a list made for five servings of a dish covers two, and covers the dish
    planned twice at two each. Compared meal by meal, cutting a plan from five
    servings to two read as a meal missing from a list bought for more.
    """
    if plan.shopping_list_id is None:
        return False
    if plan.listed_meals is None:
        return True
    listed = _servings_by_recipe(plan.listed_meals)
    planned = _servings_by_recipe(listed_meals_of(plan))
    return any(count > listed[recipe_id] for recipe_id, count in planned.items())


def _validate_entry(plan: MealPlan, entry_date: date, slot: MealSlot) -> None:
    if entry_date < plan.start_date or entry_date > plan.end_date:
        raise ConflictException(
            'ENTRY_DATE_OUT_OF_RANGE',
            get_error_message('meal_plan_entry_date_out_of_range', get_current_lang()),
        )
    if slot.value not in plan.enabled_slots:
        raise ConflictException(
            'SLOT_NOT_ENABLED',
            get_error_message('meal_plan_slot_not_enabled', get_current_lang()),
        )


async def _next_order_in_cell_async(
    db: AsyncSession, plan_id: UUID, entry_date: date, slot: MealSlot
) -> int:
    """Where a dish added to (date, slot) goes: after whatever is already there.

    A cell holds several dishes — the grid offers a "+" under every entry and
    a drag handle on each. The order within the cell is what the unique
    constraint is written on, so a new entry that does not ask for a position
    takes the next free one rather than 0, which is where the entry already in
    the cell sits.
    """
    max_order = await db.scalar(
        select(func.max(MealPlanEntry.order)).where(
            MealPlanEntry.meal_plan_id == plan_id,
            MealPlanEntry.date == entry_date,
            MealPlanEntry.slot == slot,
        )
    )
    return (max_order if max_order is not None else -1) + 1
