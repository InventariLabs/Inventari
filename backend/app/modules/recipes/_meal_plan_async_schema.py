"""Async schema helpers for meal plan services (split from _meal_plan)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import NotFoundException
from app.i18n import Language
from app.i18n.service import get_current_lang, get_shopping_label

from ._meal_plan_helpers import _get_effective_servings, meals_not_on_the_list
from .models import (
    MealPlan,
    MealPlanEntry,
    MealSlot,
    PickingSession,
)
from .nutrition_service import get_recipe_nutrition
from .schemas import (
    DailyNutritionSummary,
    MealPlanEntrySchema,
    MealPlanSchema,
)


async def _require_plan_async(
    db: AsyncSession, plan_id: UUID, org_id: UUID
) -> MealPlan:
    plan = (
        await db.scalars(
            select(MealPlan)
            .options(joinedload(MealPlan.entries).joinedload(MealPlanEntry.recipe))
            .where(MealPlan.id == plan_id, MealPlan.organization_id == org_id)
        )
    ).first()
    if plan is None:
        raise NotFoundException('meal_plan', get_current_lang())
    return plan


async def _prefetch_completed_sessions_async(
    db: AsyncSession, entries: list[MealPlanEntry], org_id: UUID
) -> dict[UUID, UUID]:
    """Which finished cooking session completes which entry: {entry_id: session_id}.

    A session started from a plan entry completes that entry, whatever day it
    finished. Any other session (started from the recipe page) completes an
    entry of its recipe dated the day it finished, in the organization's own
    zone, and each session completes one entry. It used to complete the
    earliest entry on or before that day, so a recipe cooked on Saturday
    ticked off Thursday's dinner and the week read a meal as cooked that
    nobody had made.
    """
    recipe_ids = list({e.recipe_id for e in entries if e.recipe_id})
    if not recipe_ids:
        return {}

    from app.core.public_api import core_api

    zone = await core_api.organizations.timezone_async(db, org_id)
    first = datetime.combine(min(e.date for e in entries), time.min, tzinfo=zone)
    last = datetime.combine(
        max(e.date for e in entries) + timedelta(days=1), time.min, tzinfo=zone
    )
    entry_ids = {e.id for e in entries}
    sessions = (
        await db.scalars(
            select(PickingSession)
            .where(
                PickingSession.recipe_id.in_(recipe_ids),
                PickingSession.organization_id == org_id,
                PickingSession.status == 'completed',
                or_(
                    PickingSession.meal_plan_entry_id.in_(entry_ids),
                    (PickingSession.completed_at >= first)
                    & (PickingSession.completed_at < last),
                ),
            )
            .order_by(PickingSession.completed_at.asc())
        )
    ).all()

    lookup: dict[UUID, UUID] = {}
    by_day: dict[tuple[UUID, date], list[UUID]] = {}
    for session in sessions:
        linked = session.meal_plan_entry_id
        if linked is not None:
            if linked in entry_ids:
                lookup.setdefault(linked, session.id)
        elif session.completed_at is not None:
            day = session.completed_at.astimezone(zone).date()
            by_day.setdefault((session.recipe_id, day), []).append(session.id)

    # (date, slot, order) is unique within a plan, and two slots of one day
    # ordinarily share order 0: without the slot the tie falls to the input
    # order, which differs between the plan read and a one-entry read.
    for entry in sorted(entries, key=lambda e: (e.date, e.order, e.slot)):
        if entry.id in lookup:
            continue
        queue = by_day.get((entry.recipe_id, entry.date))
        if queue:
            lookup[entry.id] = queue.pop(0)
    return lookup


async def _entry_to_schema_async(
    entry: MealPlanEntry,
    plan: MealPlan,
    db: AsyncSession,
    org_id: UUID,
    completed_lookup: dict[UUID, UUID] | None = None,
) -> MealPlanEntrySchema:
    if completed_lookup is None:
        # Read against the whole plan, so a recipe planned twice on one day
        # answers here as it does on the plan itself.
        siblings = [e for e in plan.entries if e.id != entry.id]
        completed_lookup = await _prefetch_completed_sessions_async(
            db, [*siblings, entry], org_id
        )
    session_id = completed_lookup.get(entry.id)
    is_completed = session_id is not None
    return MealPlanEntrySchema(
        id=entry.id,
        date=entry.date,
        slot=entry.slot,
        recipe_id=entry.recipe_id,
        recipe_name=entry.recipe.name if entry.recipe else '',
        recipe_image_url=entry.recipe.image_url if entry.recipe else None,
        servings=_get_effective_servings(entry, plan),
        notes=entry.notes,
        order=entry.order,
        is_completed=is_completed,
        picking_session_id=session_id,
    )


async def _build_daily_nutrition_async(
    db: AsyncSession, plan: MealPlan, org_id: UUID
) -> list[DailyNutritionSummary]:
    """Aggregate per-date nutrition totals across all plan entries.

    Uses the recipe nutrition pipeline per entry (scaled by the effective
    servings), summed by date.

    A nutrient nothing contributed to stays ``None``, not 0.0. The two say
    opposite things and the table renders them differently — "0 g" is a
    measurement, "–" is the absence of one. A plan of recipes whose
    ingredients carry no nutrition data used to read "0 g · 0 g · 0 g ·
    0 kcal", one screen away from "nutrition data for 0% of ingredients".

    A recipe contributes only when it knows all four. Half a profile summed
    into a day reads as a fact: "Carbs –, Protein –, Fat 162 g, Calories
    2136 kcal" is a calorie count for a day the application elsewhere says it
    has no data for, and the two empty columns look like zeroes rather than
    like the same missing source. Either the row describes the food or it
    says nothing about it.

    The day also carries ``coverage``, the share of its non-negligible
    ingredients that had a value for the least-measured nutrient — what the
    recipe page's coverage line states, counted per nutrient so that an
    ingredient with calories only does not vouch for the macros. A sum over a partial set is not zero where the missing
    ingredients were the only source of that nutrient (pasta is the carbs of
    a spaghetti dinner), so a 0 in a day that is not fully covered is
    reported as unknown, not as a measurement.
    """
    keys = ('calories_kcal', 'protein_g', 'fat_g', 'carbs_g')
    totals: dict[date, dict[str, float | None]] = {}
    seen: dict[date, int] = {}
    measured_by_key: dict[date, dict[str, int]] = {}
    generic_days: set[date] = set()
    for entry in plan.entries:
        if entry.recipe is None:
            continue
        servings = _get_effective_servings(entry, plan)
        nutrition = await get_recipe_nutrition(db, entry.recipe, org_id, servings)
        total = nutrition['measured_sums']
        if nutrition['generic_values']:
            generic_days.add(entry.date)
        row = totals.setdefault(entry.date, dict.fromkeys(keys))
        counted = [i for i in nutrition['ingredients'] if not i['negligible']]
        seen[entry.date] = seen.get(entry.date, 0) + len(counted)
        per_key = measured_by_key.setdefault(entry.date, dict.fromkeys(keys, 0))
        for key in keys:
            per_key[key] += sum(
                1 for i in counted if (i['nutrition'] or {}).get(key) is not None
            )
        if any(total.get(key) is None for key in keys):
            continue
        for key in keys:
            row[key] = round((row[key] or 0.0) + total[key], 2)
    days = []
    for day in sorted(totals):
        # The day is only as covered as its worst-measured nutrient: pasta with
        # calories but no macros leaves protein, fat and carbs partial.
        coverage = (
            min(measured_by_key[day].values()) / seen[day] if seen.get(day) else 1.0
        )
        row = {
            key: None
            if value == 0 and measured_by_key[day][key] < seen.get(day, 0)
            else value
            for key, value in totals[day].items()
        }
        # Two decimals must not round a partial day up to "complete": 200 of 201
        # ingredients measured is 0.995, and 1.0 would hide the missing dish.
        coverage = 1.0 if coverage == 1.0 else min(round(coverage, 2), 0.99)
        days.append(
            DailyNutritionSummary(
                date=day,
                coverage=coverage,
                generic_values=day in generic_days,
                **row,
            )
        )
    return days


async def _plan_to_schema_async(
    plan: MealPlan, db: AsyncSession, org_id: UUID
) -> MealPlanSchema:
    completed_lookup = await _prefetch_completed_sessions_async(
        db, plan.entries, org_id
    )
    entries = [
        await _entry_to_schema_async(e, plan, db, org_id, completed_lookup)
        for e in plan.entries
    ]
    daily_nutrition = await _build_daily_nutrition_async(db, plan, org_id)
    return MealPlanSchema(
        id=plan.id,
        name=plan.name,
        start_date=plan.start_date,
        end_date=plan.end_date,
        enabled_slots=[MealSlot(s) for s in plan.enabled_slots],
        default_servings=plan.default_servings,
        shopping_list_id=plan.shopping_list_id,
        meals_added_since_list=meals_not_on_the_list(plan),
        notes=plan.notes,
        entries=entries,
        daily_nutrition_summary=daily_nutrition,
        created_by=plan.created_by,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _auto_plan_name(
    start_date: date, end_date: date, lang: Language | None = None
) -> str:
    start_day = start_date.day
    end_day = end_date.day
    if start_date.year != end_date.year:
        start_month = get_shopping_label(f'month_{start_date.month}', lang)
        end_month = get_shopping_label(f'month_{end_date.month}', lang)
        return f'Plan {start_day} {start_month} {start_date.year} \u2013 {end_day} {end_month} {end_date.year}'
    if start_date.month == end_date.month:
        month_label = get_shopping_label(f'month_{start_date.month}', lang)
        return f'Plan {start_day}\u2013{end_day} {month_label}'
    start_month = get_shopping_label(f'month_{start_date.month}', lang)
    end_month = get_shopping_label(f'month_{end_date.month}', lang)
    return f'Plan {start_day} {start_month} \u2013 {end_day} {end_month}'
