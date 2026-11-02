"""An API-created product without a unit is a first-class product.

POST /items without ``uom_id`` lands in pieces, but existing on its
own card is not the whole contract: recipes have to find its stock and BoMs
have to take it as an ingredient. Both read the product through its template
and its unit, so these tests follow the creation past the 201 — through the
same door an external feed script uses.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

ITEMS_URL = '/api/v1/items'
RECIPES_URL = '/api/v1/recipes'
MAKER_RECIPES_URL = '/api/v1/maker/recipes'


def _uom_id(db: Session, symbol: str) -> str:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return str(row[0])


def _pcs_id(db: Session) -> str:
    return _uom_id(db, 'pcs')


def _create_unitless_product(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_location_id,
    name: str,
) -> dict[str, Any]:
    response = client.post(
        ITEMS_URL,
        headers=auth_headers,
        json={
            'name': name,
            'quantity': 5,
            'location_id': str(storage_location_id),
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data['uom'] is not None and data['uom']['symbol'] == 'pcs'
    assert data['template_id'] is not None
    return data


class TestApiItemWithoutUnitWorksEverywhere:
    def test_stocks_a_recipe_through_the_catalogue(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location,
    ):
        """The shelf answers a recipe asking for the product in pieces."""
        item = _create_unitless_product(
            client, auth_headers, test_storage_location.id, 'Ciecierzyca z API'
        )
        recipe = client.post(
            RECIPES_URL,
            headers=auth_headers,
            json={
                'name': 'Curry z API',
                'servings': 1,
                'instructions': 'Mix.',
                'ingredients': [
                    {
                        'name': 'Ciecierzyca z API',
                        'template_id': item['template_id'],
                        'quantity': '3',
                        'uom_id': _pcs_id(db_session),
                        'is_optional': False,
                    }
                ],
            },
        )
        assert recipe.status_code == 201, recipe.text

        availability = client.get(
            f'{RECIPES_URL}/{recipe.json()["id"]}/availability',
            headers=auth_headers,
        )
        assert availability.status_code == 200, availability.text
        ingredient = availability.json()['ingredients'][0]
        assert ingredient['status'] == 'available'
        assert ingredient['quantities_comparable'] is True
        assert ingredient['available_quantity'] == 5.0

    def test_the_minted_template_inherits_the_unit(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location,
    ):
        """The catalogue row created alongside the record does not stay
        unitless: production and the unit-weight bridge read the template,
        not the shelf."""
        item = _create_unitless_product(
            client, auth_headers, test_storage_location.id, 'Kasza z API'
        )
        row = db_session.execute(
            text('SELECT uom_id FROM product_templates WHERE id = :i'),
            {'i': item['template_id']},
        ).fetchone()
        assert row is not None
        assert str(row[0]) == _pcs_id(db_session)

    def test_joins_a_bom_as_an_ingredient(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location,
    ):
        """A formula can list the product among its inputs — in its own
        unit. A line written in a unit the product does not hold is
        refused, which only bites once the catalogue row carries the unit
        the shelf gave it."""
        item = _create_unitless_product(
            client, auth_headers, test_storage_location.id, 'Mąka z API'
        )
        output = client.post(
            '/api/v1/items/product-templates',
            headers=auth_headers,
            json={'name': 'Chleb z API'},
        )
        assert output.status_code == 201, output.text
        formula = client.post(
            MAKER_RECIPES_URL,
            headers=auth_headers,
            json={
                'name': 'Formula chleba',
                'output_template_id': output.json()['id'],
            },
        )
        assert formula.status_code == 201, formula.text

        weighed = client.post(
            f'{MAKER_RECIPES_URL}/{formula.json()["id"]}/bom-lines',
            headers=auth_headers,
            json={
                'child_template_id': item['template_id'],
                'qty_per_batch': '2',
                'unit': 'kg',
                'uom_id': _uom_id(db_session, 'kg'),
            },
        )
        # The product is held in pieces and its template says so; grams
        # against pieces is the arithmetic the ledger cannot do.
        assert weighed.status_code in (400, 409, 422), weighed.text

        line = client.post(
            f'{MAKER_RECIPES_URL}/{formula.json()["id"]}/bom-lines',
            headers=auth_headers,
            json={
                'child_template_id': item['template_id'],
                'qty_per_batch': '2',
                'unit': 'pcs',
                'uom_id': _pcs_id(db_session),
            },
        )
        assert line.status_code in (200, 201), line.text
        assert str(line.json()['child_template_id']) == str(item['template_id'])
