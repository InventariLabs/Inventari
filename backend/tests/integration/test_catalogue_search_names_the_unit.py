"""The catalogue search answers with the unit's symbol, not only its id.

``GET /warehouse/product-search`` returned ``uom_id`` for a catalogue card but
hardcoded ``uom_symbol`` to ``null``, so a form that picks a product from the
catalogue (the reorder-rule dialog) had no unit to print beside the quantity.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.uom import Uom

SEARCH_URL = '/api/v1/warehouse/product-search'
TEMPLATE_URL = '/api/v1/items/product-templates'


def _uom_id(db, symbol: str) -> str:
    return str(db.scalars(select(Uom).where(Uom.symbol == symbol)).first().id)


@pytest.mark.integration
class TestCatalogueSearchNamesTheUnit:
    def test_a_card_with_a_unit_comes_back_with_its_symbol(
        self, client, auth_headers, db_session
    ) -> None:
        created = client.post(
            TEMPLATE_URL,
            headers=auth_headers,
            json={'name': 'Symbolic widget', 'uom_id': _uom_id(db_session, 'kg')},
        )
        assert created.status_code == 201, created.text

        response = client.get(
            SEARCH_URL, headers=auth_headers, params={'q': 'Symbolic widget'}
        )

        assert response.status_code == 200, response.text
        [hit] = response.json()
        assert hit['uom_id'] == _uom_id(db_session, 'kg')
        assert hit['uom_symbol'] == 'kg'

    def test_cards_sharing_a_unit_and_cards_apart_each_get_their_own(
        self, client, auth_headers, db_session
    ) -> None:
        for name, symbol in (('Mixed one', 'kg'), ('Mixed two', 'pcs')):
            created = client.post(
                TEMPLATE_URL,
                headers=auth_headers,
                json={'name': name, 'uom_id': _uom_id(db_session, symbol)},
            )
            assert created.status_code == 201, created.text

        response = client.get(SEARCH_URL, headers=auth_headers, params={'q': 'Mixed'})

        assert response.status_code == 200, response.text
        assert {h['name']: h['uom_symbol'] for h in response.json()} == {
            'Mixed one': 'kg',
            'Mixed two': 'pcs',
        }
