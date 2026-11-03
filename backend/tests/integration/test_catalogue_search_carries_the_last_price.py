"""The catalogue search tells a purchase line what the product last cost.

The price lives on the stock records, not on the template, so a purchase
order line built from a catalogue hit had an empty price even for a product
whose records all carry one.
"""

from __future__ import annotations

import pytest

SEARCH_URL = '/api/v1/warehouse/product-search'
TEMPLATE_URL = '/api/v1/items/product-templates'


def _template(client, auth_headers, name: str) -> str:
    created = client.post(TEMPLATE_URL, headers=auth_headers, json={'name': name})
    assert created.status_code == 201, created.text
    return created.json()['id']


def _record(client, auth_headers, location_id, template_id: str, **fields) -> None:
    response = client.post(
        '/api/v1/items',
        headers=auth_headers,
        json={
            'name': 'Priced stock',
            'quantity': 1,
            'location_id': str(location_id),
            'template_id': template_id,
            **fields,
        },
    )
    assert response.status_code == 201, response.text


def _hit(client, auth_headers, query: str) -> dict:
    response = client.get(SEARCH_URL, headers=auth_headers, params={'q': query})
    assert response.status_code == 200, response.text
    [hit] = response.json()
    return hit


@pytest.mark.integration
class TestCatalogueSearchCarriesTheLastPrice:
    def test_a_product_with_a_priced_record_comes_back_with_the_price(
        self, client, auth_headers, test_storage_location
    ) -> None:
        template_id = _template(client, auth_headers, 'Priced beans')
        _record(
            client,
            auth_headers,
            test_storage_location.id,
            template_id,
            purchase_price=45.0,
        )

        hit = _hit(client, auth_headers, 'Priced beans')

        assert float(hit['purchase_price']) == 45.0

    def test_a_product_without_any_price_has_none(
        self, client, auth_headers, test_storage_location
    ) -> None:
        template_id = _template(client, auth_headers, 'Unpriced beans')
        _record(client, auth_headers, test_storage_location.id, template_id)

        assert _hit(client, auth_headers, 'Unpriced beans')['purchase_price'] is None
