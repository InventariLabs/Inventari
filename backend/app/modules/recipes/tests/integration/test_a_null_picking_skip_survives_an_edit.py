"""A seeded ingredient's picking-skip null survives a save.

The demo recipes carry NULL on ``recipe_ingredients.picking_skip`` — the
migration's "use the heuristic" contract, which ``_should_auto_skip`` still
reads. GET hands that null to the form, the form hands it back on save, and
the update schema used to refuse it (``bool = False``): every recipe with a
seeded ingredient answered 422 the moment any field was edited. The named
null is a real answer on this nullable column, so the update accepts it and
stores it as it read it.
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


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _seeded_recipe(
    client: TestClient, auth_headers: dict[str, str], db: Session
) -> dict[str, Any]:
    """A recipe whose ingredient carries NULL, the way the demo data does."""
    response = client.post(
        RECIPE_URL,
        json={
            'name': 'Pancakes with Strawberries',
            'servings': 1,
            'description': 'Old description',
            'ingredients': [
                {
                    'name': 'Flour',
                    'quantity': '200',
                    'uom_id': str(_uom_id(db, 'g')),
                    'is_optional': False,
                }
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    db.execute(
        text('UPDATE recipe_ingredients SET picking_skip = NULL WHERE recipe_id = :id'),
        {'id': created['id']},
    )
    db.commit()
    return created


def test_an_edit_sending_the_null_back_saves(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    created = _seeded_recipe(client, auth_headers, db_session)

    read = client.get(f'{RECIPE_URL}/{created["id"]}', headers=auth_headers)
    assert read.status_code == 200, read.text
    ingredient = read.json()['ingredients'][0]
    assert ingredient['picking_skip'] is None

    updated = client.put(
        f'{RECIPE_URL}/{created["id"]}',
        json={
            'description': 'New description',
            'ingredients': [{**ingredient, 'quantity': '250'}],
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()['description'] == 'New description'
    assert updated.json()['ingredients'][0]['picking_skip'] is None


def test_the_null_holds_after_a_second_read(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    created = _seeded_recipe(client, auth_headers, db_session)
    ingredient = client.get(
        f'{RECIPE_URL}/{created["id"]}', headers=auth_headers
    ).json()['ingredients'][0]

    updated = client.put(
        f'{RECIPE_URL}/{created["id"]}',
        json={'ingredients': [{**ingredient, 'sort_order': 3}]},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text

    read = client.get(f'{RECIPE_URL}/{created["id"]}', headers=auth_headers)
    assert read.status_code == 200, read.text
    assert read.json()['ingredients'][0]['picking_skip'] is None
