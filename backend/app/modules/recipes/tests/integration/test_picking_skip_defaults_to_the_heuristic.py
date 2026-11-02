"""An ingredient saved without a picking-skip answer leaves it to the heuristic.

``recipe_ingredients.picking_skip`` is tri-state: TRUE always skips, FALSE
never does, NULL lets ``_should_auto_skip`` decide (small spice amounts,
optional lines). The create schema used to default the field to FALSE, so
every ingredient written through the API — the form, an import, a duplicate —
opted out of the heuristic without anyone asking it to.
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


def _create(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    ingredient: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        RECIPE_URL,
        json={
            'name': 'Pickled Cucumbers',
            'servings': 2,
            'ingredients': [
                {'name': 'Dill', 'quantity': '5', 'uom_id': str(_uom_id(db, 'g'))}
                | ingredient
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _stored(db: Session, recipe_id: str) -> bool | None:
    value: bool | None = db.execute(
        text('SELECT picking_skip FROM recipe_ingredients WHERE recipe_id = :id'),
        {'id': recipe_id},
    ).scalar_one()
    return value


def _picking_status(
    client: TestClient, auth_headers: dict[str, str], recipe_id: str
) -> str:
    response = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        headers=auth_headers,
        json={'servings': 2},
    )
    assert response.status_code in (200, 201), response.text
    return str(response.json()['items_to_pick'][0]['status'])


def test_an_ingredient_without_an_answer_is_stored_for_the_heuristic(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    created = _create(client, auth_headers, db_session, {})

    assert created['ingredients'][0]['picking_skip'] is None
    assert _stored(db_session, created['id']) is None
    assert _picking_status(client, auth_headers, created['id']) == 'skipped'


def test_an_explicit_never_skip_is_kept(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    created = _create(client, auth_headers, db_session, {'picking_skip': False})

    assert created['ingredients'][0]['picking_skip'] is False
    assert _stored(db_session, created['id']) is False
    assert _picking_status(client, auth_headers, created['id']) != 'skipped'
