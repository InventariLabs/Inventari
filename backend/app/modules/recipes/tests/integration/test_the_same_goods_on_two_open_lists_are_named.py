"""Two doors that make a shopping list must say when they overlap.

"Add what is missing" on a recipe and "Generate shopping list" on a meal plan
each write a list of their own. A cook who used both ended up with the same
flour on two open lists and nothing on either screen saying so. The lists are
still written (they are two plans, and merging them silently would change a
list somebody is already shopping from); the answer names what each goods
already stands on, and where.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

RECIPE_URL = '/api/v1/recipes'
PLAN_URL = f'{RECIPE_URL}/meal-plans'
LISTS_URL = '/api/v1/shopping-lists'


def _grams(db: Session) -> str:
    row = db.execute(text("SELECT id FROM uoms WHERE symbol = 'g'")).fetchone()
    assert row is not None
    return str(row[0])


def _recipe(
    client: TestClient, headers: dict[str, str], grams: str, name: str = 'Pancakes'
) -> str:
    response = client.post(
        RECIPE_URL,
        json={
            'name': name,
            'servings': 1,
            'ingredients': [
                {'name': 'Flour', 'quantity': '300', 'uom_id': grams},
                {'name': 'Eggs', 'quantity': '120', 'uom_id': grams},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _plan_of(client: TestClient, headers: dict[str, str], recipe_id: str) -> str:
    today = date.today()
    plan_id = client.post(
        PLAN_URL,
        json={
            'start_date': today.isoformat(),
            'end_date': (today + timedelta(days=6)).isoformat(),
            'enabled_slots': ['LUNCH'],
            'default_servings': 1,
        },
        headers=headers,
    ).json()['id']
    client.post(
        f'{PLAN_URL}/{plan_id}/entries',
        json={
            'date': today.isoformat(),
            'slot': 'LUNCH',
            'recipe_id': recipe_id,
            'order': 0,
        },
        headers=headers,
    )
    return str(plan_id)


def _names(overlaps: list[dict[str, Any]]) -> set[str]:
    return {line['name'] for line in overlaps}


class TestOverlapIsReported:
    def test_a_plan_list_names_the_goods_a_recipe_list_already_holds(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        grams = _grams(db_session)
        recipe_id = _recipe(client, auth_headers, grams)
        first = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()['on_other_lists'] == []

        plan_id = _plan_of(client, auth_headers, recipe_id)
        second = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )

        assert second.status_code == 200, second.text
        body = second.json()
        assert body['shopping_list_id'] != first.json()['shopping_list_id']
        assert _names(body['on_other_lists']) == {'Flour', 'Eggs'}
        assert {line['list_id'] for line in body['on_other_lists']} == {
            first.json()['shopping_list_id']
        }
        assert all(line['list_name'] for line in body['on_other_lists'])

    def test_a_recipe_list_names_the_goods_a_plan_list_already_holds(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        grams = _grams(db_session)
        recipe_id = _recipe(client, auth_headers, grams)
        plan_id = _plan_of(client, auth_headers, recipe_id)
        generated = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )
        assert generated.status_code == 200, generated.text
        assert generated.json()['on_other_lists'] == []

        added = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )

        assert added.status_code == 200, added.text
        body = added.json()
        assert _names(body['on_other_lists']) == {'Flour', 'Eggs'}
        assert (
            body['on_other_lists'][0]['list_id']
            == (generated.json()['shopping_list_id'])
        )

    def test_a_bought_line_is_not_an_overlap(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        grams = _grams(db_session)
        recipe_id = _recipe(client, auth_headers, grams)
        first = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        ).json()
        items = client.get(
            f'{LISTS_URL}/{first["shopping_list_id"]}/items', headers=auth_headers
        ).json()['items']
        for item in items:
            bought = client.patch(
                f'{LISTS_URL}/{first["shopping_list_id"]}/items/{item["id"]}/purchase',
                headers=auth_headers,
            )
            assert bought.status_code == 200, bought.text

        plan_id = _plan_of(client, auth_headers, recipe_id)
        second = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )

        assert second.status_code == 200, second.text
        assert second.json()['on_other_lists'] == []

    def test_the_list_being_refreshed_is_not_its_own_overlap(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        grams = _grams(db_session)
        recipe_id = _recipe(client, auth_headers, grams)
        plan_id = _plan_of(client, auth_headers, recipe_id)
        for _ in range(2):
            response = client.post(
                f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
            )
            assert response.status_code == 200, response.text
            assert response.json()['on_other_lists'] == []


class TestTheSameGoodsInAnotherUnitAreNamed:
    """A line in kilograms names a list carrying the goods in grams.

    Grams and kilograms measure one thing, so 300 g of flour on one list and
    1 kg on another are the same goods on two lists. A unit of another
    measure -- pieces against grams -- is not the same line.
    """

    def _uom(self, db: Session, symbol: str) -> str:
        row = db.execute(
            text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
        ).fetchone()
        assert row is not None, f'UOM {symbol!r} is not seeded'
        return str(row[0])

    def _list_of(
        self,
        client: TestClient,
        headers: dict[str, str],
        name: str,
        ingredients: list[dict[str, str]],
    ) -> dict[str, Any]:
        recipe = client.post(
            RECIPE_URL,
            json={'name': name, 'servings': 1, 'ingredients': ingredients},
            headers=headers,
        )
        assert recipe.status_code == 201, recipe.text
        added = client.post(
            f'{RECIPE_URL}/{recipe.json()["id"]}/add-to-shopping-list',
            json={'servings': 1},
            headers=headers,
        )
        assert added.status_code == 200, added.text
        body: dict[str, Any] = added.json()
        return body

    def test_kilograms_name_the_list_holding_grams(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        grams, kilos = self._uom(db_session, 'g'), self._uom(db_session, 'kg')
        pieces = self._uom(db_session, 'pcs')
        first = self._list_of(
            client,
            auth_headers,
            'Pancakes',
            [
                {'name': 'Flour', 'quantity': '300', 'uom_id': grams},
                {'name': 'Eggs', 'quantity': '120', 'uom_id': grams},
            ],
        )

        second = self._list_of(
            client,
            auth_headers,
            'Bread',
            [
                {'name': 'Flour', 'quantity': '1', 'uom_id': kilos},
                {'name': 'Eggs', 'quantity': '2', 'uom_id': pieces},
            ],
        )

        assert second['shopping_list_id'] != first['shopping_list_id']
        assert [
            (line['name'], line['list_id']) for line in second['on_other_lists']
        ] == [('Flour', first['shopping_list_id'])]
