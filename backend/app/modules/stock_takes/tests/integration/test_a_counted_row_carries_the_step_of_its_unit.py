"""A row on the counting screen says what its unit lets a person type.

The rule about how finely a quantity may be stated already exists, in one
place: ``uom.rounding``, checked at every door where a person types a number.
The counting screen is one of those doors, and it is the one where the typing
happens on a phone in front of a shelf — so the screen has to know the rule
before the save, not learn it from a refusal afterwards.

Knowing it needs the step on the wire. The symbol alone says ``kg`` but not
that a kilogram may be stated in thousandths, and a screen that guesses ends
up inventing a rule of its own: it rounded every count to a whole number, so
2.1 kg became 2 kg without a word.
"""

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus

pytestmark = pytest.mark.integration


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f'the seeded catalogue has no {symbol}'
    return uom


def _count_over(
    db: Session,
    *,
    user: User,
    location: StorageLocation,
    item: Item,
    uom: Uom,
) -> StockTake:
    stock_take = StockTake(
        user_id=user.id,
        organization_id=location.organization_id,
        storage_location_id=location.id,
        name='A count of something weighed',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db.add(stock_take)
    db.flush()
    db.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            uom_id=uom.id,
            system_quantity=Decimal('2.300'),
        )
    )
    db.commit()
    return stock_take


def test_a_row_on_a_divisible_unit_carries_its_step(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
    test_item: Item,
    test_user: User,
) -> None:
    kilogram = _uom(db_session, 'kg')
    stock_take = _count_over(
        db_session,
        user=test_user,
        location=test_storage_location,
        item=test_item,
        uom=kilogram,
    )

    response = client.get(f'/api/v1/stock-takes/{stock_take.id}', headers=auth_headers)

    assert response.status_code == status.HTTP_200_OK
    line = response.json()['items'][0]
    assert line['uom_symbol'] == 'kg'
    assert Decimal(str(line['uom_rounding'])) == Decimal('0.001')


def test_a_row_on_a_counted_unit_carries_a_whole_step(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
    test_item: Item,
    test_user: User,
) -> None:
    piece = _uom(db_session, 'pcs')
    stock_take = _count_over(
        db_session,
        user=test_user,
        location=test_storage_location,
        item=test_item,
        uom=piece,
    )

    response = client.get(f'/api/v1/stock-takes/{stock_take.id}', headers=auth_headers)

    assert response.status_code == status.HTTP_200_OK
    line = response.json()['items'][0]
    assert line['uom_symbol'] == 'pcs'
    assert Decimal(str(line['uom_rounding'])) == Decimal('1')


def test_a_row_without_a_unit_carries_no_step(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
    test_item: Item,
    test_user: User,
) -> None:
    stock_take = StockTake(
        user_id=test_user.id,
        organization_id=test_storage_location.organization_id,
        storage_location_id=test_storage_location.id,
        name='A count of something unmeasured',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    db_session.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=test_item.id,
            item_name=test_item.name,
            system_quantity=Decimal('1'),
        )
    )
    db_session.commit()

    response = client.get(f'/api/v1/stock-takes/{stock_take.id}', headers=auth_headers)

    assert response.status_code == status.HTTP_200_OK
    line = response.json()['items'][0]
    assert line['uom_symbol'] is None
    assert line['uom_rounding'] is None
