"""A picking session ready to take from the shelf, for tests that drive a pick.

The recipe asks for one product in pieces, so a scan of a record counted in
pieces takes exactly what the recipe names, with no unit bridge and, for a
whole number, no package to open.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.uom import Uom
from app.modules.recipes.models import (
    PickingSession,
    PickingSessionItem,
    Recipe,
    RecipeIngredient,
)


async def a_picking_session(
    db: AsyncSession, keeper: UserContextDTO, template_id: UUID, needed: Decimal
) -> tuple[UUID, UUID]:
    """An active session whose recipe asks for *needed* pieces of the product.

    Returns the session and the ingredient it is picking.
    """
    pieces = await db.scalar(select(Uom.id).where(Uom.symbol == 'pcs'))
    recipe = Recipe(
        organization_id=keeper.organization_id,
        name=f'Porridge {uuid4().hex[:6]}',
        servings=1,
        created_by=keeper.id,
    )
    db.add(recipe)
    await db.flush()
    ingredient = RecipeIngredient(
        recipe_id=recipe.id,
        template_id=template_id,
        name='Rice',
        quantity=needed,
        uom_id=pieces,
    )
    session = PickingSession(
        organization_id=keeper.organization_id,
        recipe_id=recipe.id,
        user_id=keeper.id,
        servings=1,
    )
    db.add_all([ingredient, session])
    await db.flush()
    db.add(
        PickingSessionItem(
            session_id=session.id, ingredient_id=ingredient.id, status='pending'
        )
    )
    await db.flush()
    return session.id, ingredient.id
