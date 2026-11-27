"""The asset doors refuse a price the record cannot hold.

The bulk form answers it with a validation error naming the field; the
spreadsheet import refuses the row and names the cell.
"""

from __future__ import annotations

import json

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize('price', ['1e12', '-1'])
def test_bulk_create_refuses_a_price_out_of_range(
    price: str,
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_storage_location: StorageLocation,
) -> None:
    response = client.post(
        '/api/v1/equipment/items/bulk',
        headers=eq_auth_headers,
        json={
            'name': 'Dell Latitude 5540',
            'location_id': str(eq_storage_location.id),
            'purchase_price': price,
            'entries': [{'serial_number': 'SN-PRICE-1'}],
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, response.text
    assert any('purchase_price' in e['loc'] for e in response.json()['detail'])


@pytest.mark.parametrize('price', ['1000000000000', '-1'])
def test_import_refuses_the_row_and_names_the_cell(
    price: str,
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_storage_location: StorageLocation,
) -> None:
    response = client.post(
        '/api/v1/equipment/import/execute',
        headers=eq_auth_headers,
        files={
            'file': (
                'assets.csv',
                f'name,serial,price\nPriced,SN-PRICE-2,{price}\n'.encode(),
                'text/csv',
            )
        },
        data={
            'mapping_json': json.dumps(
                {'name': 'name', 'serial_number': 'serial', 'purchase_price': 'price'}
            ),
            'default_location_id': str(eq_storage_location.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    assert body['imported'] == 0
    assert body['errors'][0]['code'] == 'IMPORT_PRICE_INVALID'
    assert price in body['errors'][0]['error']
