"""A footer summing prices in mixed currencies adds złoty to euro.

The statistics tile sums a record's price only when the currency is the
organization's own or unstated, and counts what it left out. The list
footer, reading the same column under the same ``purchase_price`` source,
summed every price as one number — so an organization holding a single
euro-priced record saw the tile say one thing and the footer say another
by exactly the money that was never in the organization's currency. Two
amounts in two currencies have no sum; the footer keeps the tile's policy
and counts the records it cannot price into ``unpriced_count``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration

_MODULES = ['core', 'items', 'locations', 'categories']


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def plain_org(db_session: Session) -> Organization:
    """A fresh organization: no cost ledger, purchase prices on the cards."""
    return ModuleTestHelper(db_session).create_org('Card Priced Org', _MODULES)


@pytest.fixture
def plain_user(db_session: Session, plain_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        plain_org, email='card-pricer@example.com', role='manager'
    )


@pytest.fixture
def plain_headers(h: ModuleTestHelper, plain_user: User) -> dict[str, str]:
    return h.get_auth_headers(plain_user)


@pytest.fixture
def plain_location(
    db_session: Session, plain_org: Organization, plain_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Card Pantry', 'PANTRY', organization_id=plain_org.id
    )
    return h.create_storage_location(
        plain_org, storage_type, plain_user, name='Card shelf'
    )


def _buy(
    client: TestClient,
    headers: dict[str, str],
    storage_id: object,
    *,
    name: str,
    quantity: str,
    price: str,
) -> str:
    response = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': name,
            'quantity': quantity,
            'purchase_price': price,
            'location_id': str(storage_id),
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


def _price_in_euros(db: Session, item_id: str) -> None:
    """A card priced in a currency the organization does not keep."""
    item = db.get(Item, item_id)
    assert item is not None
    item.purchase_price = Decimal('100.00')
    item.currency = 'EUR'
    db.commit()


class TestTheFooterCountsOneCurrency:
    def test_a_foreign_currency_price_never_joins_the_sum(
        self, client, plain_headers, plain_location, plain_org, db_session: Session
    ) -> None:
        ours = _buy(
            client,
            plain_headers,
            plain_location.id,
            name='Rice',
            quantity='2',
            price='10.00',
        )
        imported = _buy(
            client,
            plain_headers,
            plain_location.id,
            name='Imported olive oil',
            quantity='1',
            price='100.00',
        )
        _price_in_euros(db_session, imported)
        assert ours

        response = client.get('/api/v1/items/aggregates', headers=plain_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['value_source'] == 'purchase_price'
        # Two amounts in two currencies have no sum: the euro price is left
        # out, not added on top of the złoty one.
        assert data['total_value'] == pytest.approx(20.0)
        # And the left-out record is named, not silently missing.
        assert data['unpriced_count'] == 1

    def test_a_stated_organisation_currency_price_still_counts(
        self, client, plain_headers, plain_location, plain_org, db_session: Session
    ) -> None:
        item_id = _buy(
            client,
            plain_headers,
            plain_location.id,
            name='Rice',
            quantity='2',
            price='10.00',
        )
        # The organization states PLN, the card states PLN: ours, counted.
        plain_org.currency = 'PLN'
        item = db_session.get(Item, item_id)
        assert item is not None
        item.currency = 'PLN'
        db_session.commit()

        response = client.get('/api/v1/items/aggregates', headers=plain_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['value_source'] == 'purchase_price'
        assert data['total_value'] == pytest.approx(20.0)
        assert data['unpriced_count'] == 0
