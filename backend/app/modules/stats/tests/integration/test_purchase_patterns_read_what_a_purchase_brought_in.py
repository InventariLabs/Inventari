"""What a product cost is what its purchases brought in, whatever happened next.

A purchase record changes after the day it was bought: a unit of it is
opened (split off as a record of its own), some of it is used, the last of it
is used up and the record is filed under Consumed. None of that changes what
was bought or what it cost, so the purchase patterns read the quantity a
record was born with and keep a record that has nothing left.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

URL = '/api/v1/stats/purchase-patterns'


def _buy(
    client: TestClient, headers: dict[str, str], shelf: StorageLocation, name: str
) -> str:
    """Four bottles at 30.00 each, entered by hand."""
    response = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': name,
            'quantity': 4,
            'purchase_price': '30.00',
            'location_id': str(shelf.id),
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    item_id: str = response.json()['id']
    return item_id


def _use(client: TestClient, headers: dict[str, str], item_id: str, qty: int) -> None:
    response = client.patch(
        f'/api/v1/items/{item_id}/consume', headers=headers, json={'quantity': qty}
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _row(client: TestClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    response = client.get(URL, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    rows = {r['name']: r for r in response.json()['top_recurring_products']}
    row: dict[str, Any] = rows.get(name, {})
    return row


def test_opening_and_using_a_unit_do_not_lower_what_was_spent(
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location: StorageLocation,
) -> None:
    first = _buy(client, auth_headers, test_storage_location, 'Review Oil B')
    second = _buy(client, auth_headers, test_storage_location, 'Review Oil B')

    opened = client.post(
        f'/api/v1/items/{first}/use-partially', headers=auth_headers, json={}
    )
    assert opened.status_code == status.HTTP_200_OK, opened.text
    _use(client, auth_headers, second, 1)

    row = _row(client, auth_headers, 'Review Oil B')

    assert row['total_purchases_last_6_months'] == 2
    assert row['total_spent'] == 240.0
    assert row['avg_price'] == 120.0
    assert row['avg_quantity'] == 4.0


def test_a_purchase_used_up_stays_a_purchase(
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location: StorageLocation,
) -> None:
    _buy(client, auth_headers, test_storage_location, 'Oats')
    used_up = _buy(client, auth_headers, test_storage_location, 'Oats')

    _use(client, auth_headers, used_up, 4)

    row = _row(client, auth_headers, 'Oats')

    assert row['total_purchases_last_6_months'] == 2
    assert row['total_spent'] == 240.0
