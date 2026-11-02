"""Reading an active picking session again, with the shelf re-checked.

A session is a list of decisions the user has already made ("this one is in
the basket") laid over a reading of the shelf that ages the moment it is
taken. Linking an ingredient to a product mid-session used to mean throwing
the session away, because there was no way to ask for that reading again.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from ._picking_session_helpers import _get_session_or_404, _ingredient_to_checklist_item
from .schemas import PickingStartResponse

# What the user decided, as opposed to what the shelf happened to hold.
_USER_DECIDED = frozenset({'picked', 'skipped'})


async def read_picking_session(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
) -> PickingStartResponse:
    """Return the session's checklist, recomputed for the rows still open.

    Rows the user has already acted on keep their stored status — a pick is
    a fact about the basket, not about the shelf, and re-deriving it would
    undo work. Everything else is resolved afresh, so a product linked or
    restocked a minute ago shows up.
    """
    from .services import get_recipe

    lang = get_current_lang()
    session = await _get_session_or_404(db, session_id, org_id)
    recipe = await get_recipe(db, session.recipe_id, org_id)
    if not recipe:
        raise NotFoundException('recipe', lang)

    from ._scaling import resolve_multiplier

    multiplier = resolve_multiplier(recipe.servings, session.servings, session.scale)
    stored = {row.ingredient_id: row for row in session.items if row.ingredient_id}

    uoms_by_id = {
        uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    items_to_pick = []
    for ingredient in recipe.ingredients:
        item = await _ingredient_to_checklist_item(
            ingredient, multiplier, db, org_id, uoms_by_id
        )
        row = stored.get(ingredient.id)
        if row is not None and row.status in _USER_DECIDED:
            item.status = row.status
        elif row is not None and row.status != item.status:
            # Keep the stored checklist in step with what the sheet now shows,
            # so completing the session does not act on a stale reading.
            row.status = item.status
        items_to_pick.append(item)

    await db.flush()

    return PickingStartResponse(
        picking_session_id=session.id,
        recipe_name=recipe.name,
        servings=session.servings,
        scale=session.scale,
        items_to_pick=items_to_pick,
    )
