"""Integration tests: stock matched by name covers an ingredient on every door.

A recipe imported with plain names — "Rice", not a link to the pantry's
Rice — finds its goods by name: the recipe screen calls them "Similar". The
meal plan's generator deducted that stock and left the rice off the list;
the recipe screen's "Add missing" button and the list's "From recipes"
dialog put the whole requirement on it, under a counter that read
"Missing 1". Same recipe, same pantry, two shopping lists.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import put_on_shelf, run_in_async_session

RECIPE_URL = '/api/v1/recipes'
PLAN_URL = f'{RECIPE_URL}/meal-plans'

pytestmark = pytest.mark.integration


def _grams(db: Session) -> str:
    row = db.execute(text("SELECT id FROM uoms WHERE symbol = 'g'")).fetchone()
    assert row is not None
    return str(row[0])


def _shelve(
    db: Session,
    engine: AsyncEngine,
    user: User,
    location: StorageLocation,
    name: str,
    quantity: Decimal,
) -> None:
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name=name,
        uom_id=uuid.UUID(_grams(db)),
    )
    db.add(template)
    db.commit()

    async def _put(session: AsyncSession) -> None:
        await put_on_shelf(session, user, template, location.id, quantity)

    run_in_async_session(engine, _put)
    db.expire_all()


def _lines(
    client: TestClient, auth_headers: dict[str, str], list_id: str
) -> set[tuple[str, Decimal]]:
    items = client.get(f'/api/v1/shopping-lists/{list_id}/items', headers=auth_headers)
    assert items.status_code == 200, items.text
    return {(i['name'], Decimal(str(i['quantity']))) for i in items.json()['items']}


class TestEveryDoorReadsOneRule:
    def test_the_meal_plan_and_add_missing_put_the_same_lines_on_the_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        # Enough rice to cover the recipe, too little chicken, no soy sauce.
        for name, quantity in (('Rice', '1000'), ('Chicken breast', '100')):
            _shelve(
                db_session,
                async_engine_fixture,
                test_user,
                test_storage_location,
                name,
                Decimal(quantity),
            )
        grams = _grams(db_session)
        recipe = client.post(
            RECIPE_URL,
            json={
                'name': 'Chicken fried rice',
                'servings': 1,
                'instructions': 'Fry.',
                'ingredients': [
                    {'name': 'Rice', 'quantity': '200', 'uom_id': grams},
                    {'name': 'Chicken breast', 'quantity': '300', 'uom_id': grams},
                    {'name': 'Soy sauce', 'quantity': '20', 'uom_id': grams},
                ],
            },
            headers=auth_headers,
        )
        assert recipe.status_code == 201, recipe.text
        recipe_id = recipe.json()['id']

        availability = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability',
            params={'servings': 1},
            headers=auth_headers,
        )
        assert availability.status_code == 200, availability.text
        statuses = {i['name']: i['status'] for i in availability.json()['ingredients']}
        # The precondition: the rice is found by its name, not by a link.
        assert statuses['Rice'] == 'available_approx'

        today = date.today()
        plan = client.post(
            PLAN_URL,
            json={
                'start_date': today.isoformat(),
                'end_date': (today + timedelta(days=6)).isoformat(),
                'enabled_slots': ['LUNCH'],
                'default_servings': 1,
            },
            headers=auth_headers,
        )
        assert plan.status_code == 201, plan.text
        plan_id = plan.json()['id']
        entry = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        assert entry.status_code in (200, 201), entry.text
        generated = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )
        assert generated.status_code == 200, generated.text

        added = client.post(
            f'{RECIPE_URL}/shopping-list/add-from-recipes',
            json={'recipe_ids': [recipe_id], 'servings': 1},
            headers=auth_headers,
        )
        assert added.status_code == 200, added.text

        from_the_plan = _lines(
            client, auth_headers, generated.json()['shopping_list_id']
        )
        from_the_recipe = _lines(client, auth_headers, added.json()['shopping_list_id'])
        assert from_the_recipe == from_the_plan
        assert from_the_plan == {
            ('Chicken breast', Decimal('200')),
            ('Soy sauce', Decimal('20')),
        }
        assert added.json()['added_count'] == 2
