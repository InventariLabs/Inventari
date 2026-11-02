"""A surplus row says what the system thought was there, not nought.

The row was created with ``system_quantity=0`` on the reasoning that the item
"was not expected at this location". Finalising writes the count as an
absolute quantity, so an item the system holds seven of, added to a count and
counted as three, ends the count at three — and the four that vanished are
recorded nowhere. The growth cap does not see it either: it skips rows whose
system quantity is falsy, and nought is falsy.

The item was also looked up across the whole organization, so the thing being
"found" could be sitting on a different shelf entirely. Counting it here then
overwrote the quantity it has there. A count covers a location and its
descendants; something outside that tree is not a surplus in this count.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _add_surplus(
    client: TestClient,
    headers: dict[str, str],
    stock_take_id: Any,
    item_id: Any,
    counted: str,
) -> Any:
    return client.post(
        f'/api/v1/stock-takes/{stock_take_id}/items',
        headers=headers,
        json={'item_id': str(item_id), 'counted_quantity': counted},
    )


def test_a_surplus_row_carries_the_stock_the_item_already_had(
    client: TestClient,
    auth_headers: dict[str, str],
    test_stock_take: Any,
    test_item: Item,
    db_session: Session,
) -> None:
    """Seven on the system, three on the shelf: a shortage of four, recorded."""
    test_item.quantity = Decimal('7')
    db_session.commit()

    response = _add_surplus(client, auth_headers, test_stock_take.id, test_item.id, '3')

    assert response.status_code == status.HTTP_201_CREATED, response.text
    data = response.json()
    assert Decimal(str(data['system_quantity'])) == Decimal('7')
    assert Decimal(str(data['counted_quantity'])) == Decimal('3')
    assert data['is_discrepancy'] == 1


def test_a_row_for_stock_nobody_had_still_starts_at_nought(
    client: TestClient,
    auth_headers: dict[str, str],
    test_stock_take: Any,
    test_item: Item,
    db_session: Session,
) -> None:
    """The control: a genuine surplus is a genuine surplus."""
    test_item.quantity = Decimal('0')
    db_session.commit()

    response = _add_surplus(
        client, auth_headers, test_stock_take.id, test_item.id, '15'
    )

    assert response.status_code == status.HTTP_201_CREATED, response.text
    data = response.json()
    assert Decimal(str(data['system_quantity'])) == Decimal('0')
    assert data['is_discrepancy'] == 1


def test_something_on_another_shelf_is_not_a_surplus_here(
    client: TestClient,
    auth_headers: dict[str, str],
    test_stock_take: Any,
    test_storage_location: StorageLocation,
    test_user: Any,
    db_session: Session,
) -> None:
    """Counting it here would overwrite the quantity it has there."""
    elsewhere = StorageLocation(
        organization_id=test_storage_location.organization_id,
        name='Another shelf entirely',
        storage_type_id=test_storage_location.storage_type_id,
        created_by=test_user.id,
    )
    db_session.add(elsewhere)
    db_session.flush()
    stranger = Item(
        organization_id=test_storage_location.organization_id,
        storage_location_id=elsewhere.id,
        name='Lives on another shelf',
        quantity=Decimal('7'),
    )
    db_session.add(stranger)
    db_session.commit()

    response = _add_surplus(client, auth_headers, test_stock_take.id, stranger.id, '3')

    # A conflict, like the refusal to add the same item twice: the request is
    # well formed, the shelf it names is not this one.
    assert response.status_code == status.HTTP_409_CONFLICT, response.text
    db_session.refresh(stranger)
    assert stranger.quantity == Decimal('7')
