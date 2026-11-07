"""An ingredient line with an amount and no unit is refused by the API.

"Salt 2" could not be weighed against the shelf and reached the shopping list
as "Salt 2 —". The recipe form refuses it and so does the import; the create
and update endpoints are the doors every other client uses, so they refuse it
too, with a coded 400 that names the ingredient.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def a_unit_on_every_recipe_line() -> None:
    """This module sends the lines as written — no unit is added for it."""


def _uom_id(db_session: Session, symbol: str) -> str:
    row = db_session.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return str(uuid.UUID(str(row[0])))


def _recipe(ingredients: list[dict[str, Any]]) -> dict[str, Any]:
    return {'name': 'Brine', 'servings': 1, 'ingredients': ingredients}


def _stored_count(db_session: Session, name: str) -> int:
    row = db_session.execute(
        text('SELECT count(*) FROM recipes WHERE name = :n'), {'n': name}
    ).scalar_one()
    return int(row)


def test_create_refuses_a_named_line_without_a_unit(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    response = client.post(
        RECIPE_URL,
        json=_recipe([{'name': 'Salt', 'quantity': 2}]),
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'RECIPE_INGREDIENT_UNIT_MISSING'
    assert 'Salt' in detail['message']
    assert _stored_count(db_session, 'Brine') == 0


def test_update_refuses_a_named_line_without_a_unit(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    created = client.post(
        RECIPE_URL,
        json=_recipe(
            [{'name': 'Water', 'quantity': 1, 'uom_id': _uom_id(db_session, 'g')}]
        ),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    recipe = created.json()

    response = client.put(
        f'{RECIPE_URL}/{recipe["id"]}',
        json={
            'ingredients': [
                {'id': recipe['ingredients'][0]['id'], 'name': 'Water', 'quantity': 1},
                {'name': 'Salt', 'quantity': 2},
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()['detail']['code'] == 'RECIPE_INGREDIENT_UNIT_MISSING'
    stored = client.get(f'{RECIPE_URL}/{recipe["id"]}', headers=auth_headers).json()
    assert [i['name'] for i in stored['ingredients']] == ['Water']
    assert stored['ingredients'][0]['uom_id'] == _uom_id(db_session, 'g')


def test_a_line_with_a_unit_is_still_stored(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    response = client.post(
        RECIPE_URL,
        json=_recipe(
            [{'name': 'Salt', 'quantity': 2, 'uom_id': _uom_id(db_session, 'g')}]
        ),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
