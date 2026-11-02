"""The snapshot holds every quantity the shelf it copies can hold.

``items.quantity`` is ``numeric(12, 3)`` — up to 999,999,999.999 — and a stock
take copies it into ``stock_take_items.system_quantity``, which was
``numeric(10, 3)`` and held a third of those digits. One item over
9,999,999.999 made the INSERT overflow, so opening a count on that shelf
answered 500 with the driver's NumericValueOutOfRangeError instead of a
stock take. The row found during the count copies the same column, and
answered the same way. A snapshot cannot refuse what its source may hold:
the row carries the source's width.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User

#: The largest quantity the items column stores — its numeric(12, 3) bound.
HUGE = Decimal('999999999.999')


def _open_count(
    client: TestClient,
    auth_headers: dict[str, str],
    storage: StorageLocation,
    name: str,
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/stock-takes',
        headers=auth_headers,
        json={'name': name, 'location_id': str(storage.id)},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    stock_take: dict[str, Any] = response.json()
    return stock_take


@pytest.mark.integration
class TestTheSnapshotHoldsWhatTheShelfHolds:
    """A shelf whose item is past the row's own column still opens a count."""

    def test_creating_a_count_on_a_shelf_holding_the_largest_quantity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        test_item.quantity = HUGE
        db_session.commit()

        stock_take = _open_count(
            client, auth_headers, test_storage_location, 'Ceiling edge'
        )

        rows = client.get(
            f'/api/v1/stock-takes/{stock_take["id"]}/items', headers=auth_headers
        ).json()['items']
        row = next(r for r in rows if r['item_id'] == str(test_item.id))
        assert Decimal(str(row['system_quantity'])) == HUGE

    def test_a_row_for_an_item_found_during_the_count_carries_what_is_there(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        stock_take = _open_count(
            client, auth_headers, test_storage_location, 'Found during the count'
        )

        # The item lands on the shelf after the snapshot was taken, so it is a
        # surplus row — and the surplus row copies the same column.
        found = Item(
            organization_id=test_storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Found later',
            quantity=HUGE,
            expiry_date=date.today() + timedelta(days=30),
        )
        db_session.add(found)
        db_session.commit()

        response = client.post(
            f'/api/v1/stock-takes/{stock_take["id"]}/items',
            headers=auth_headers,
            json={'item_id': str(found.id), 'counted_quantity': 5},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert Decimal(str(response.json()['system_quantity'])) == HUGE
