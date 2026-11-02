"""``enable_cost_calculation`` decides whether a recipe has a cost at all.

The setting was offered, saved and read by nobody: the cost section showed
whatever the setting said. The cost door now answers by it, and says so in
the payload so a screen can leave the cost out instead of printing an empty
one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

RECIPE_URL = '/api/v1/recipes'
SETTINGS_URL = '/api/v1/modules/recipes/settings'


def _priced_recipe(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        RECIPE_URL,
        json={
            'name': 'Priced Stew',
            'servings': 2,
            'ingredients': [
                {'name': 'Saffron', 'quantity': '3', 'price': '2.50'},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def test_the_cost_is_there_until_the_setting_says_otherwise(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    recipe_id = _priced_recipe(client, auth_headers)

    body = client.get(f'{RECIPE_URL}/{recipe_id}/cost', headers=auth_headers).json()

    assert body['enabled'] is True
    assert body['estimated_cost'] == 7.5


def test_a_recipe_has_no_cost_once_the_setting_is_off(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    recipe_id = _priced_recipe(client, auth_headers)
    off = client.put(
        SETTINGS_URL, json={'enable_cost_calculation': False}, headers=auth_headers
    )
    assert off.status_code == 200, off.text

    response = client.get(f'{RECIPE_URL}/{recipe_id}/cost', headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['enabled'] is False
    assert body['estimated_cost'] is None
    assert body['ingredients'] == []


def test_the_price_typed_on_an_ingredient_survives_saving_and_editing(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        '/api/v1/recipes',
        json={
            'name': 'Saved price',
            'servings': 1,
            'ingredients': [{'name': 'Saffron', 'quantity': '3', 'price': '2.50'}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body['ingredients'][0]['price'] == '2.50'

    ingredient = body['ingredients'][0]
    edited = client.put(
        f'/api/v1/recipes/{body["id"]}',
        json={
            'ingredients': [
                {
                    'id': ingredient['id'],
                    'name': 'Saffron',
                    'quantity': '3',
                    'price': '4',
                }
            ]
        },
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()['ingredients'][0]['price'] == '4.00'
