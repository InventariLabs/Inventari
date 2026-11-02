from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from ._picking_session_helpers import (
    _ingredient_to_checklist_item,
)
from .models import PickingSession, PickingSessionItem
from .schemas import (
    PickingStartResponse,
)


async def record_cooking_session(
    db: AsyncSession,
    recipe_id: UUID,
    org_id: UUID,
    user_id: UUID,
    servings: int | None,
    session_id: UUID | None = None,
) -> PickingSession:
    """Record a finished cook, or close the one it continues.

    The step-by-step mode never touches the shelf, so until now it also
    never appeared in the cooking history — and its rating, asked for on
    the "Bon appétit" screen, landed on whatever session happened to have
    closed last: a wrong day, wrong servings, "no items picked" under a
    note about a different dinner. Finishing a cook records its own entry
    — its own date, its own servings, nothing picked.

    One dinner is one entry, though. Picking the ingredients and then
    cooking them step by step is one meal, and the screen says which
    session it continues: given a ``session_id`` this closes that run
    instead of opening a second entry beside it — which would leave the
    picked one unrated and hang the note on an entry reading "nothing
    picked", the very shape this task exists to remove.
    """
    from .services import get_recipe

    lang = get_current_lang()
    recipe = await get_recipe(db, recipe_id, org_id)
    if not recipe:
        raise NotFoundException('recipe', lang)

    finished_at = datetime.now(UTC)
    if session_id is not None:
        continued = await _session_to_continue(
            db, session_id, recipe_id, org_id, user_id
        )
        if continued is None:
            raise NotFoundException('picking_session', lang)
        # The entry is dated by the cook, not by the shelf: a run closed in
        # the morning and cooked in the evening reads as the evening's dinner,
        # on the day the meal plan buckets it under. The run's own start stays
        # as it was.
        continued.status = 'completed'
        continued.completed_at = finished_at
        if servings is not None:
            continued.servings = servings
        await db.flush()
        await db.refresh(continued)
        return continued

    session = PickingSession(
        organization_id=org_id,
        recipe_id=recipe_id,
        user_id=user_id,
        servings=servings if servings is not None else recipe.servings,
        status='completed',
        created_at=finished_at,
        completed_at=finished_at,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def _session_to_continue(
    db: AsyncSession,
    session_id: UUID,
    recipe_id: UUID,
    org_id: UUID,
    user_id: UUID,
) -> PickingSession | None:
    """The run this cook says it continues, when it is this cook's to close.

    Scoped to the organization, the recipe and the person cooking: an id
    from another kitchen names nothing here, and a shared recipe does not
    let one member write a rating onto another member's dinner.

    And scoped in time to one dinner: a run that already carries a rating or
    a note is a finished meal, not a thread to keep pulling. Without that,
    cooking the same recipe a second time named the same run again and the
    second rating overwrote the first evening's — one entry where there were
    two meals, and the earlier note gone for good. Offered such a run, this
    names nothing, and the cook opens an entry of its own.
    """
    result = await db.execute(
        select(PickingSession).where(
            PickingSession.id == session_id,
            PickingSession.organization_id == org_id,
            PickingSession.recipe_id == recipe_id,
            PickingSession.user_id == user_id,
            PickingSession.status.in_(('active', 'completed')),
            PickingSession.rating.is_(None),
            PickingSession.notes.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def start_picking_session(
    db: AsyncSession,
    recipe_id: UUID,
    org_id: UUID,
    user_id: UUID,
    servings: int | None,
    scale: Decimal | None = None,
    meal_plan_entry_id: UUID | None = None,
) -> PickingStartResponse:
    from ._picking_refresh import read_picking_session
    from .services import get_recipe

    lang = get_current_lang()
    result = await db.execute(
        select(PickingSession)
        .where(
            PickingSession.recipe_id == recipe_id,
            PickingSession.organization_id == org_id,
            PickingSession.status == 'active',
        )
        .with_for_update()
    )
    unfinished = list(result.scalars().all())

    # An unfinished session is work someone did, and cancelling it puts every
    # ingredient back on the shelf. Doing that on sight meant a meal that had
    # been cooked came back into stock the next time anyone opened this
    # dialog — nothing on screen said so, and the only trace was two rows in
    # the item history that cancel each other out. So the session is handed
    # back to be finished; cancelling it is a thing the reader asks for, with
    # a button that says what it does.
    if unfinished:
        if meal_plan_entry_id is not None:
            # Cook Now on a card means this card, even when the cook in hand
            # was begun from its sibling.
            unfinished[0].meal_plan_entry_id = meal_plan_entry_id
        resumed = await read_picking_session(db, unfinished[0].id, org_id)
        return resumed.model_copy(update={'resumed': True})

    recipe = await get_recipe(db, recipe_id, org_id)
    if not recipe:
        raise NotFoundException('recipe', lang)

    from ._scaling import resolve_multiplier

    requested_servings = servings or recipe.servings
    multiplier = resolve_multiplier(recipe.servings, servings, scale)

    # A scale session keeps the whole count the fraction stands on: the
    # multiplier lives in its own column, so a session of 1.4 is stored as
    # 1.4 — not folded into the integer ``servings``, where it could only
    # land rounded.
    session = PickingSession(
        id=uuid.uuid4(),
        organization_id=org_id,
        recipe_id=recipe_id,
        user_id=user_id,
        meal_plan_entry_id=meal_plan_entry_id,
        servings=recipe.servings if scale is not None else requested_servings,
        scale=scale,
        status='active',
    )
    db.add(session)

    uoms_by_id = {
        uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    items_to_pick = []
    for ing in recipe.ingredients:
        item = await _ingredient_to_checklist_item(
            ing, multiplier, db, org_id, uoms_by_id
        )
        items_to_pick.append(item)

    for ing, todo in zip(recipe.ingredients, items_to_pick, strict=True):
        db.add(
            PickingSessionItem(
                id=uuid.uuid4(),
                session_id=session.id,
                ingredient_id=todo.ingredient_id,
                # Snapshot taken here, not on consume: the session must stay
                # readable even if the recipe drops the ingredient afterwards.
                ingredient_name=todo.name,
                # The sheet already put this on the ingredient unit's step;
                # asking for the same step again keeps the snapshot and the
                # sheet reading the same number.
                required_quantity=core_api.uoms.round_up(
                    Decimal(str(todo.quantity_to_pick)),
                    uoms_by_id.get(ing.uom_id) if ing.uom_id else None,
                ),
                required_uom_symbol=todo.uom_symbol,
                item_id=None,
                quantity_consumed=None,
                status=todo.status,
            )
        )

    await db.flush()

    return PickingStartResponse(
        picking_session_id=session.id,
        recipe_name=recipe.name,
        servings=session.servings,
        scale=session.scale,
        items_to_pick=items_to_pick,
    )
