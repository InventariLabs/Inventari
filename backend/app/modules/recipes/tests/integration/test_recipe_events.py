"""Integration tests for recipes module events.

Verifies that the recipe.* events are emitted transactionally on:
- recipe creation            (recipe.created)
- picking session completion (recipe.picking_completed)
- meal plan shopping list    (recipe.meal_plan_generated)

In TESTING mode the event bus dispatches inline after commit (flush_pending),
so subscribing + hitting the API is a full end-to-end check. A handler reads
what it is told about from a session of its own, as a production consumer
does: the write has to be committed by then, and a request whose transaction
is rolled back must announce nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.public_api import core_api
from app.database import dispatch_committed_events, get_async_db
from app.main import app
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.recipes.models.meal_plan import MealPlan
from app.modules.recipes.models.picking import PickingSession
from app.modules.recipes.models.recipe import Recipe
from tests.integration._shelf import post_on_shelf

RECIPE_URL = '/api/v1/recipes'
PLAN_URL = '/api/v1/recipes/meal-plans'


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Event Test Recipe',
        'servings': 2,
        'ingredients': [],
    }
    base.update(overrides)
    return base


def _plan_payload(**overrides: Any) -> dict[str, Any]:
    today = date.today()
    base = {
        'name': 'Event Test Plan',
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=6)).isoformat(),
        'enabled_slots': ['LUNCH', 'DINNER'],
        'default_servings': 2,
    }
    base.update(overrides)
    return base


def _listen_committed(
    event: str, db_session: Session, read: Callable[[Session, Any], Any]
) -> list[Any]:
    """Subscribe to *event*; each delivery appends *read*'s answer.

    *read* runs on a fresh session of its own, so it sees only what has been
    committed — the view a consumer of the event has.
    """
    seen: list[Any] = []

    def handler(payload: Any) -> None:
        with Session(bind=db_session.get_bind()) as fresh:
            seen.append(read(fresh, payload))

    core_api.events.subscribe(event, handler)
    return seen


@contextmanager
def _requests_roll_back(async_engine_fixture: Any) -> Iterator[None]:
    """Serve requests on a session that is rolled back instead of committed."""
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )

    async def rolled_back() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session
            await session.rollback()
            # Whatever is still buffered goes out here; the rollback must have
            # taken the recipe's event with it, and the service must not have
            # sent it on its own before.
            await dispatch_committed_events(session)

    committing = app.dependency_overrides[get_async_db]
    app.dependency_overrides[get_async_db] = rolled_back
    try:
        yield
    finally:
        app.dependency_overrides[get_async_db] = committing


@pytest.mark.integration
class TestRecipeEvents:
    def test_recipe_created_event_emitted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Any,
        async_engine_fixture: Any,
    ) -> None:
        received: list[Any] = []
        core_api.events.subscribe('recipe.created', received.append)
        committed = _listen_committed(
            'recipe.created',
            db_session,
            lambda fresh, payload: fresh.scalar(
                select(func.count())
                .select_from(Recipe)
                .where(Recipe.id == uuid.UUID(payload.recipe_id))
            ),
        )

        with _requests_roll_back(async_engine_fixture):
            r = client.post(
                RECIPE_URL,
                json=_recipe_payload(name='Rolled back'),
                headers=auth_headers,
            )
        assert r.status_code == 201
        assert received == []

        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Created by event test'),
            headers=auth_headers,
        )
        assert r.status_code == 201
        recipe_id = r.json()['id']

        assert len(received) == 1
        assert committed == [1]
        payload = received[0]
        assert payload.recipe_id == recipe_id
        assert payload.name == 'Created by event test'
        assert payload.organization_id is not None

    def test_picking_completed_event_emitted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Any,
        async_engine_fixture: Any,
    ) -> None:
        received: list[Any] = []
        core_api.events.subscribe('recipe.picking_completed', received.append)
        committed = _listen_committed(
            'recipe.picking_completed',
            db_session,
            lambda fresh, payload: fresh.scalar(
                select(PickingSession.status).where(
                    PickingSession.id == uuid.UUID(payload.session_id)
                )
            ),
        )

        grams = db_session.scalar(select(Uom.id).where(Uom.symbol == 'g'))
        assert grams is not None, "'g' is not seeded"
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Makaron event',
            uom_id=grams,
        )
        db_session.add(template)
        db_session.commit()
        item_id = post_on_shelf(
            client, auth_headers, template, test_storage_location.id, '500'
        )['id']

        recipe_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Event picking recipe',
                ingredients=[
                    {
                        'name': 'Makaron event',
                        'template_id': str(template.id),
                        'uom_id': str(grams),
                        'quantity': '200',
                        'is_optional': False,
                    }
                ],
            ),
            headers=auth_headers,
        )
        recipe_id = recipe_r.json()['id']

        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': item_id},
            headers=auth_headers,
        )
        with _requests_roll_back(async_engine_fixture):
            complete_r = client.post(
                f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
                headers=auth_headers,
            )
        assert complete_r.status_code == 200
        assert received == []

        complete_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        assert complete_r.status_code == 200

        assert len(received) == 1
        assert committed == ['completed']
        payload = received[0]
        assert payload.session_id == session_id
        assert payload.recipe_id == recipe_id
        assert payload.servings == 2
        assert len(payload.items_consumed) == 1
        assert payload.items_consumed[0]['item_id'] == item_id
        assert payload.organization_id is not None

    def test_meal_plan_generated_event_emitted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Any,
        async_engine_fixture: Any,
    ) -> None:
        received: list[Any] = []
        core_api.events.subscribe('recipe.meal_plan_generated', received.append)
        committed = _listen_committed(
            'recipe.meal_plan_generated',
            db_session,
            lambda fresh, payload: str(
                fresh.scalar(
                    select(MealPlan.shopping_list_id).where(
                        MealPlan.id == uuid.UUID(payload.plan_id)
                    )
                )
            ),
        )

        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL, json=_recipe_payload(), headers=auth_headers
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        with _requests_roll_back(async_engine_fixture):
            gen_r = client.post(
                f'{PLAN_URL}/{plan_id}/generate-shopping-list',
                headers=auth_headers,
            )
        assert gen_r.status_code == 200
        assert received == []

        gen_r = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list',
            headers=auth_headers,
        )
        assert gen_r.status_code == 200
        shopping_list_id = gen_r.json()['shopping_list_id']

        assert len(received) == 1
        assert committed == [shopping_list_id]
        payload = received[0]
        assert payload.plan_id == plan_id
        assert payload.shopping_list_id == shopping_list_id
        assert payload.to_buy_count == 0
        assert payload.organization_id is not None
