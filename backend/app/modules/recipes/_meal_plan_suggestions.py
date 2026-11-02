"""Async recipe suggestions for meal plans (split from _meal_plan)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ._availability import build_stock_context, stock_coverage
from .models import (
    MealPlanEntry,
    PickingSession,
    Recipe,
    RecipeIngredient,
)
from .schemas import RecipeAvailability, SuggestedRecipe
from .services import get_recipe_availability

_AVAILABILITY_HARD_FILTER = 0.3
_EXPIRY_URGENCY_DAYS = 3
_MAX_CANDIDATES = 50
_URGENCY_BY_DAYS_LEFT = {0: 1.0, 1: 0.8, 2: 0.6}


async def _batch_load_recent_recipe_ids_async(
    db: AsyncSession, org_id: UUID
) -> set[UUID]:
    cutoff = datetime.now(UTC) - timedelta(days=14)
    recent_cooked = (
        await db.scalars(
            select(PickingSession.recipe_id)
            .where(
                PickingSession.organization_id == org_id,
                PickingSession.status == 'completed',
                PickingSession.completed_at >= cutoff,
            )
            .distinct()
        )
    ).all()
    return set(recent_cooked)


def _expiry_urgency_score(
    availability: RecipeAvailability, reference_date: date
) -> float:
    """Score the recipe by the soonest expiry among the stock backing it.

    ``best_item`` is the FEFO winner of whatever the ingredient resolved
    to, so availability has already found the very item this score is
    about — a separate template-keyed query could only ever see hard links,
    and for an ingredient without one it returned 0.0. On real data that
    was every ingredient, so every recipe scored zero and the 0.3 hard
    filter below then emptied the whole suggestion list.
    """
    scores: list[float] = []
    for ingredient in availability.ingredients:
        best = ingredient.best_item
        if best is None or not best.expiry_date:
            continue
        days_left = (date.fromisoformat(best.expiry_date) - reference_date).days
        if days_left < 0 or days_left > _EXPIRY_URGENCY_DAYS:
            continue
        scores.append(_URGENCY_BY_DAYS_LEFT.get(days_left, 0.4))
    return max(scores) if scores else 0.0


def _variety_score_from_cache(recipe: Recipe, recent_recipe_ids: set[UUID]) -> float:
    if recipe.id in recent_recipe_ids:
        return 0.3
    return 1.0


def _time_bonus_score(recipe: Recipe) -> float:
    if recipe.prep_time_minutes is None:
        return 0.5
    if recipe.prep_time_minutes <= 30:
        return 1.0
    if recipe.prep_time_minutes <= 60:
        return 0.7
    return 0.4


async def get_suggestions_async(
    db: AsyncSession,
    org_id: UUID,
    target_date: date,
    slot: str,
    count: int = 5,
    plan_id: UUID | None = None,
) -> list[SuggestedRecipe]:
    plan_recipe_ids_on_date: set[UUID] = set()
    if plan_id is not None:
        existing_entries = (
            await db.scalars(
                select(MealPlanEntry.recipe_id).where(
                    MealPlanEntry.meal_plan_id == plan_id,
                    MealPlanEntry.date == target_date,
                )
            )
        ).all()
        plan_recipe_ids_on_date = set(existing_entries)

    recipes = (
        (
            await db.scalars(
                select(Recipe)
                .options(
                    joinedload(Recipe.ingredients).joinedload(RecipeIngredient.template)
                )
                .where(Recipe.organization_id == org_id)
                .order_by(Recipe.updated_at.desc())
                .limit(_MAX_CANDIDATES)
            )
        )
        .unique()
        .all()
    )
    recipes = list(recipes)

    recent_recipe_ids = await _batch_load_recent_recipe_ids_async(db, org_id)

    stock = await build_stock_context(
        db, [ing for r in recipes for ing in r.ingredients], org_id
    )

    scored: list[SuggestedRecipe] = []

    for recipe in recipes:
        if recipe.id in plan_recipe_ids_on_date:
            continue

        avail = await get_recipe_availability(
            db,
            recipe,
            org_id,
            recipe.servings or 1,
            context=stock,
        )
        availability_pct = avail.match_percentage

        if availability_pct < _AVAILABILITY_HARD_FILTER:
            continue

        a_score = availability_pct
        e_score = _expiry_urgency_score(avail, target_date)
        v_score = _variety_score_from_cache(recipe, recent_recipe_ids)
        t_score = _time_bonus_score(recipe)

        total = 0.4 * a_score + 0.3 * e_score + 0.2 * v_score + 0.1 * t_score

        in_stock, required = stock_coverage(recipe, avail)
        scored.append(
            SuggestedRecipe(
                recipe_id=recipe.id,
                name=recipe.name,
                image_url=recipe.image_url,
                prep_time_minutes=recipe.prep_time_minutes,
                availability_pct=round(availability_pct, 2),
                ingredients_available=in_stock,
                ingredients_total=required,
                expiry_urgency_score=round(e_score, 2),
                score=round(total, 3),
            )
        )

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:count]
