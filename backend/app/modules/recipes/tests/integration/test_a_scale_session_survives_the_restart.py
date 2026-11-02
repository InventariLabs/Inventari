"""A picking session carries its own multiplier, and it survives the restart.

A session started from a scale factor (``scale=1.4``) stores the fraction in
its own column: ``servings`` keeps one whole count and stays readable for
every session before this, ``NULL`` in ``scale`` means the session was
portioned by servings, and nothing needs a backfill. Until the column, a
fraction could only reach the session folded into ``servings`` — rounded to
a whole number — so a session of 1.4 became one of 3 (or 2, depending on
the recipe's own count) and disagreed with itself on the next read.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.recipes.models.picking import PickingSession
from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _recipe_with_flour(
    db: AsyncSession, household: Organization, user: User
) -> Recipe:
    recipe = Recipe(
        name='Batch Bread',
        organization_id=household.id,
        servings=2,
        created_by=user.id,
    )
    db.add(recipe)
    await db.flush()
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            name='Flour',
            quantity=Decimal('100'),
        )
    )
    await db.flush()
    return recipe


class TestAScaleSessionSurvivesTheRestart:
    async def test_the_fraction_lands_in_its_own_column_and_comes_back(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        from app.modules.recipes._picking_session import start_picking_session

        db = real_async_db_session
        recipe = await _recipe_with_flour(db, async_test_household, async_test_user)
        await db.commit()

        started = await start_picking_session(
            db,
            recipe.id,
            async_test_household.id,
            async_test_user.id,
            servings=None,
            scale=Decimal('1.4'),
        )

        # The sheet is derived from the multiplier: 100 g of flour for two
        # servings, read at 1.4.
        assert started.scale == Decimal('1.4')
        flour = next(item for item in started.items_to_pick if item.name == 'Flour')
        assert flour.quantity_to_pick == Decimal('140')

        # The restart: the session is read again from what the database
        # holds, in a session that has never seen the objects above.
        session_id = started.picking_session_id
        org_id = async_test_household.id
        db.expire_all()
        row = await db.get(PickingSession, session_id)
        assert row is not None
        assert row.scale == Decimal('1.4')
        # The whole count stays whole — the fraction lives in its column,
        # not folded into a servings number it cannot fit.
        assert row.servings == 2

        from app.modules.recipes._picking_refresh import read_picking_session

        reread = await read_picking_session(db, session_id, org_id)
        flour_again = next(
            item for item in reread.items_to_pick if item.name == 'Flour'
        )
        assert flour_again.quantity_to_pick == Decimal('140')
        assert reread.scale == Decimal('1.4')

    async def test_a_servings_session_stays_what_it_was(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """No scale is the portioned session of every recipe before this.

        Pins the other side of the column: ``NULL`` reads as a multiplier
        derived from ``servings`` exactly as the session always did.
        """
        from app.modules.recipes._picking_session import start_picking_session

        db = real_async_db_session
        recipe = await _recipe_with_flour(db, async_test_household, async_test_user)
        await db.commit()

        started = await start_picking_session(
            db,
            recipe.id,
            async_test_household.id,
            async_test_user.id,
            servings=6,
        )
        assert started.scale is None
        flour = next(item for item in started.items_to_pick if item.name == 'Flour')
        # Six of two servings: three times the recipe.
        assert flour.quantity_to_pick == Decimal('300')
