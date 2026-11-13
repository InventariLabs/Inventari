"""A whole requirement reached through a division is not rounded past it.

A recipe written for three servings asks for three eggs; cooked for five it
asks for five. The multiplier is the quotient 5/3, and ``Decimal`` keeps 28
significant digits of it, so three times the quotient lands a few units in
the last place above five — and the requirement, which rounds up so that
needing part of a step never reads as none, was answered as six eggs.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> str:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return str(row[0])


def _three_servings_of_eggs(
    client: TestClient, auth_headers: dict[str, str], uom_id: str
) -> str:
    ingredient: dict[str, Any] = {
        'name': 'Eggs',
        'quantity': '3',
        'uom_id': uom_id,
        'is_optional': False,
    }
    response = client.post(
        RECIPE_URL,
        json={'name': 'Three eggs', 'servings': 3, 'ingredients': [ingredient]},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


class TestAScaledRequirement:
    def test_five_servings_of_a_three_serving_recipe_ask_for_five_eggs(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        pieces = _uom_id(db_session, 'pcs')
        recipe_id = _three_servings_of_eggs(client, auth_headers, pieces)

        response = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?servings=5',
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        [eggs] = response.json()['ingredients']
        assert Decimal(str(eggs['required_quantity'])) == Decimal('5')
        # Nothing was rounded from: the card has no explanation to give.
        assert eggs['required_quantity_unrounded'] is None
