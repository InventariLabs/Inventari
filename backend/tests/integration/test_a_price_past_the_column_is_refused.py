"""A purchase price the column cannot hold is a refusal naming the field.

``items.purchase_price`` keeps ten digits, two of them after the point, and a
price below zero is nobody's price. Every door that takes one from a request —
create, edit, scan, the bulk asset form — answers it with a validation error,
and a price restated into the card's unit past the same ceiling is refused by
name before anything is written.
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
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

ITEMS_URL = '/api/v1/items'
TOO_BIG = ['1e12', '100000000', '99999999.995', '-1']


def _create(
    client: TestClient,
    headers: dict[str, str],
    storage: StorageLocation,
    price: str,
    **extra: object,
):
    return client.post(
        ITEMS_URL,
        headers=headers,
        json={
            'name': 'Priced thing',
            'location_id': str(storage.id),
            'quantity': '1',
            'purchase_price': price,
            **extra,
        },
    )


def _names_the_price(response) -> bool:
    return any('purchase_price' in error['loc'] for error in response.json()['detail'])


@pytest.mark.parametrize('price', TOO_BIG)
def test_create_refuses_a_price_out_of_range(
    price: str,
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
) -> None:
    response = _create(client, auth_headers, test_storage_location, price)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, response.text
    assert _names_the_price(response), response.text
    assert db_session.scalars(select(Item)).first() is None


@pytest.mark.parametrize('price', TOO_BIG)
def test_edit_refuses_a_price_out_of_range(
    price: str,
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_household: Organization,
    test_storage_location: StorageLocation,
) -> None:
    item = Item(
        name='Priced thing',
        organization_id=test_household.id,
        storage_location_id=test_storage_location.id,
        quantity=Decimal('1'),
        purchase_price=Decimal('3.50'),
    )
    db_session.add(item)
    db_session.commit()

    response = client.put(
        f'{ITEMS_URL}/{item.id}',
        headers=auth_headers,
        json={'purchase_price': price},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, response.text
    assert _names_the_price(response), response.text
    db_session.expire_all()
    db_session.refresh(item)
    assert item.purchase_price == Decimal('3.50')


@pytest.mark.parametrize('price', ['0', '99999999.99'])
def test_the_ends_of_the_range_are_kept(
    price: str,
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location: StorageLocation,
) -> None:
    response = _create(client, auth_headers, test_storage_location, price)

    assert response.status_code == status.HTTP_201_CREATED, response.text
    assert Decimal(str(response.json()['purchase_price'])) == Decimal(price)


def test_a_scan_refuses_a_price_out_of_range(
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location: StorageLocation,
) -> None:
    response = client.post(
        '/api/v1/labels/scan/5901234123457/assign',
        headers=auth_headers,
        json={
            'name': 'Scanned thing',
            'location_id': str(test_storage_location.id),
            'purchase_price': '1e12',
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, response.text
    assert _names_the_price(response), response.text


def test_a_price_restated_past_the_ceiling_is_refused_by_name(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
) -> None:
    """A price per gram becomes a price per kilogram a thousand times as big."""
    h = ModuleTestHelper(db_session)
    kg, g = h.get_uom('kg'), h.get_uom('g')
    card = client.post(
        f'{ITEMS_URL}/product-templates',
        headers=auth_headers,
        json={'name': 'Saffron', 'uom_id': str(kg.id)},
    )
    assert card.status_code == status.HTTP_201_CREATED, card.text

    response = _create(
        client,
        auth_headers,
        test_storage_location,
        '500000',
        name='Saffron',
        template_id=card.json()['id'],
        uom_id=str(g.id),
        quantity='100',
        unit_confirmed_over_template=True,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    assert response.json()['detail']['code'] == 'ITEM_PRICE_ABOVE_CEILING'
    db_session.expire_all()
    assert db_session.scalars(select(Item)).first() is None


def test_an_opened_package_keeps_a_stored_price_as_it_is(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_household: Organization,
    test_storage_location: StorageLocation,
) -> None:
    """The bounds are for what a request names, not for a row copied onward."""
    item = Item(
        name='Old row',
        organization_id=test_household.id,
        storage_location_id=test_storage_location.id,
        quantity=Decimal('2'),
        uom_id=ModuleTestHelper(db_session).get_uom('pcs').id,
        purchase_price=Decimal('-1.00'),
    )
    db_session.add(item)
    db_session.commit()

    response = client.post(
        f'{ITEMS_URL}/{item.id}/use-partially', headers=auth_headers, json={}
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert Decimal(str(response.json()['purchase_price'])) == Decimal('-1.00')
