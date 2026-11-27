"""A quantity restated into the card's unit is held to the column's ceiling.

The bound a request's quantity is checked against belongs to the unit it was
named in; a quantity in kilograms on a product kept in grams is a thousand
times as big once restated, and is refused by name before anything is written.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

ITEMS_URL = '/api/v1/items'


def _gram_card(client: TestClient, headers: dict[str, str], h: ModuleTestHelper) -> str:
    card = client.post(
        f'{ITEMS_URL}/product-templates',
        headers=headers,
        json={'name': 'Saffron', 'uom_id': str(h.get_uom('g').id)},
    )
    assert card.status_code == status.HTTP_201_CREATED, card.text
    return str(card.json()['id'])


def test_a_new_record_refuses_a_quantity_restated_past_the_ceiling(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
) -> None:
    h = ModuleTestHelper(db_session)
    template_id = _gram_card(client, auth_headers, h)

    response = client.post(
        ITEMS_URL,
        headers=auth_headers,
        json={
            'name': 'Saffron',
            'template_id': template_id,
            'location_id': str(test_storage_location.id),
            'quantity': '999999999',
            'uom_id': str(h.get_uom('kg').id),
            'unit_confirmed_over_template': True,
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    assert response.json()['detail']['code'] == 'ITEM_QUANTITY_ABOVE_CEILING'
    db_session.expire_all()
    assert db_session.scalars(select(Item)).first() is None


def test_an_edit_refuses_a_quantity_restated_past_the_ceiling(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
) -> None:
    """Only an empty record can change unit; its edit holds the same ceiling."""
    h = ModuleTestHelper(db_session)
    template_id = _gram_card(client, auth_headers, h)
    created = client.post(
        ITEMS_URL,
        headers=auth_headers,
        json={
            'name': 'Saffron',
            'template_id': template_id,
            'location_id': str(test_storage_location.id),
            'quantity': '0',
            'uom_id': str(h.get_uom('g').id),
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text

    response = client.put(
        f'{ITEMS_URL}/{created.json()["id"]}',
        headers=auth_headers,
        json={
            'quantity': '999999999',
            'uom_id': str(h.get_uom('kg').id),
            'unit_confirmed_over_template': True,
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    assert response.json()['detail']['code'] == 'ITEM_QUANTITY_ABOVE_CEILING'
    db_session.expire_all()
    item = db_session.scalars(select(Item)).one()
    assert item.quantity == Decimal('0')
