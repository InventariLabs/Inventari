"""A count posts what somebody counted, over stock nobody has touched since.

The system quantity is frozen when the count is created, and finalising writes
the counted number as an absolute quantity without ever looking at what the
stock is now. A movement made between the counting and the posting — a
delivery received, a picking done, a correction typed — was therefore erased
without a word, and the shelf ended at a number that was true an hour ago.

The count keeps saying how much there is, which is what a count is for. What
it stops doing is saying it about a shelf that has changed since: the row goes
back to be counted again, against the quantity the system now holds. A delta
would have invented a state nobody ever observed, and can go below zero;
refusing hands the conflict to the person who can walk to the shelf.
"""

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus

pytestmark = pytest.mark.integration


def _count_of(
    db: Session,
    *,
    user: User,
    location: StorageLocation,
    item: Item,
    counted: Decimal,
) -> StockTake:
    stock_take = StockTake(
        user_id=user.id,
        organization_id=location.organization_id,
        storage_location_id=location.id,
        name='A count someone will overtake',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db.add(stock_take)
    db.flush()
    db.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=item.quantity,
            counted_quantity=counted,
        )
    )
    db.commit()
    return stock_take


def test_a_movement_after_the_count_is_not_erased(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
    test_item: Item,
    test_user: User,
) -> None:
    test_item.quantity = Decimal('10')
    db_session.commit()
    stock_take = _count_of(
        db_session,
        user=test_user,
        location=test_storage_location,
        item=test_item,
        counted=Decimal('8'),
    )

    # Two more arrive while the count sits waiting to be posted.
    test_item.quantity = Decimal('12')
    db_session.commit()

    response = client.post(
        f'/api/v1/stock-takes/{stock_take.id}/complete',
        headers=auth_headers,
        json={'apply_adjustments': True},
    )

    assert response.status_code == status.HTTP_409_CONFLICT, response.text
    assert response.json()['detail']['code'] == 'STOCK_TAKE_STOCK_MOVED'
    db_session.refresh(test_item)
    assert test_item.quantity == Decimal('12')


def test_the_row_goes_back_to_be_counted_against_what_is_there_now(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
    test_item: Item,
    test_user: User,
) -> None:
    """Recounting against the stale number would refuse for ever."""
    test_item.quantity = Decimal('10')
    db_session.commit()
    stock_take = _count_of(
        db_session,
        user=test_user,
        location=test_storage_location,
        item=test_item,
        counted=Decimal('8'),
    )
    test_item.quantity = Decimal('12')
    db_session.commit()

    client.post(
        f'/api/v1/stock-takes/{stock_take.id}/complete',
        headers=auth_headers,
        json={'apply_adjustments': True},
    )

    db_session.expire_all()
    row = (
        db_session.query(StockTakeItem)
        .filter(StockTakeItem.stock_take_id == stock_take.id)
        .one()
    )
    assert row.recount_requested is True
    assert row.system_quantity == Decimal('12')


def test_a_shelf_nobody_touched_still_posts(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
    test_item: Item,
    test_user: User,
) -> None:
    """The control: the count is still the count."""
    test_item.quantity = Decimal('10')
    db_session.commit()
    stock_take = _count_of(
        db_session,
        user=test_user,
        location=test_storage_location,
        item=test_item,
        counted=Decimal('8'),
    )

    response = client.post(
        f'/api/v1/stock-takes/{stock_take.id}/complete',
        headers=auth_headers,
        json={'apply_adjustments': True},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    db_session.refresh(test_item)
    assert test_item.quantity == Decimal('8')
