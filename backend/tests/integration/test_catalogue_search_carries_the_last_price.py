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


def _record(client, auth_headers, location_id, template_id: str, **fields) -> str:
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
    return response.json()['id']


def _use_up(client, auth_headers, item_id: str, quantity: int = 1) -> None:
    response = client.patch(
        f'/api/v1/items/{item_id}/consume',
        headers=auth_headers,
        json={'quantity': quantity},
    )
    assert response.status_code == 200, response.text


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

    def test_a_product_used_up_keeps_its_price(
        self, client, auth_headers, test_storage_location
    ) -> None:
        # Buying again is what an empty shelf is for: the price it last cost
        # is wanted most when nothing of the product is left.
        template_id = _template(client, auth_headers, 'Exhausted beans')
        item_id = _record(
            client,
            auth_headers,
            test_storage_location.id,
            template_id,
            purchase_price=99.0,
        )
        _use_up(client, auth_headers, item_id)

        assert (
            float(_hit(client, auth_headers, 'Exhausted beans')['purchase_price']) == 99
        )

    def test_the_latest_price_wins_even_when_that_record_is_used_up(
        self, client, auth_headers, test_storage_location
    ) -> None:
        template_id = _template(client, auth_headers, 'Repriced beans')
        _record(
            client,
            auth_headers,
            test_storage_location.id,
            template_id,
            purchase_price=45.0,
            quantity=5,
        )
        latest = _record(
            client,
            auth_headers,
            test_storage_location.id,
            template_id,
            purchase_price=50.0,
        )
        _use_up(client, auth_headers, latest)

        assert (
            float(_hit(client, auth_headers, 'Repriced beans')['purchase_price']) == 50
        )

    def test_a_deleted_record_is_no_price_on_record(
        self, client, auth_headers, test_storage_location
    ) -> None:
        # Deleting says the record should not count, often because it was
        # entered wrong; its price is not offered for the next order.
        template_id = _template(client, auth_headers, 'Deleted beans')
        item_id = _record(
            client,
            auth_headers,
            test_storage_location.id,
            template_id,
            purchase_price=45.0,
        )
        deleted = client.delete(f'/api/v1/items/{item_id}', headers=auth_headers)
        assert deleted.status_code == 204, deleted.text

        assert _hit(client, auth_headers, 'Deleted beans')['purchase_price'] is None
