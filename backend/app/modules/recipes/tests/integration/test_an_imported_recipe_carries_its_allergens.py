"""A recipe imported from JSON carries the allergens its ingredient names suggest.

The review screen pre-ticks what the names suggest, for the cook to correct,
and a direct import saves the same; a line that names its own allergens keeps
them. The recipe then reads its allergens on its page and in its export, as
one typed through the recipe form does.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _payload(*ingredients: dict[str, Any]) -> dict[str, Any]:
    return {
        'format': 'json',
        'data': {
            'name': 'Cheese omelette',
            'servings': 1,
            'ingredients': [
                {'quantity': 50, 'uom': 'g', **ingredient} for ingredient in ingredients
            ],
        },
    }


def test_the_review_screen_pre_ticks_what_the_names_suggest(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        f'{RECIPE_URL}/import/preview',
        json=_payload(
            {'name': 'Eggs'},
            {'name': 'Butter'},
            {'name': 'Cheddar cheese'},
            {'name': 'Water'},
        ),
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    by_name = {i['name']: i['allergens'] for i in response.json()['ingredients']}
    assert by_name == {
        'Eggs': ['eggs'],
        'Butter': ['milk'],
        'Cheddar cheese': ['milk'],
        'Water': [],
    }


def test_a_direct_import_saves_milk_on_the_butter_line(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        f'{RECIPE_URL}/import',
        json=_payload({'name': 'Eggs'}, {'name': 'Butter'}),
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_201_CREATED, response.text
    recipe = response.json()
    lines = {i['name']: i['allergens'] for i in recipe['ingredients']}
    assert lines == {'Eggs': ['eggs'], 'Butter': ['milk']}
    assert recipe['allergens'] == ['eggs', 'milk']

    exported = client.get(
        f'{RECIPE_URL}/{recipe["id"]}/export?format=json', headers=auth_headers
    )
    assert exported.status_code == status.HTTP_200_OK, exported.text
    assert {i['name']: i['allergens'] for i in exported.json()['ingredients']} == (
        lines
    )


def test_a_line_that_names_its_allergens_keeps_them(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        f'{RECIPE_URL}/import/preview',
        json=_payload({'name': 'Butter', 'allergens': ['soy']}),
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert response.json()['ingredients'][0]['allergens'] == ['soy']
