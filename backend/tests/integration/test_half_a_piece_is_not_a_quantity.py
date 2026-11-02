"""A unit counted in whole pieces is not counted in halves.

Every unit says the smallest step it is counted in — ``rounding`` — and a
piece says one. The rule was written and then asked in one place only: when a
document line is built. Every other way a quantity reaches the shelf skipped
it, so "2.5 pieces" went in through the quantity endpoint and through a stock
take without anybody objecting, and the number that came back out was
whatever Postgres had rounded it to.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.fixture
def prec_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Precision Org', ['core', 'items', 'locations', 'categories', 'stock_takes']
    )


@pytest.fixture
def prec_user(db_session: Session, prec_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        prec_org, email='precision@example.com', role='manager'
    )


@pytest.fixture
def prec_headers(db_session: Session, prec_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(prec_user)


@pytest.fixture
def prec_location(
    db_session: Session, prec_org: Organization, prec_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type: StorageType = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=prec_org.id
    )
    return h.create_storage_location(
        prec_org, storage_type, prec_user, name='Counted shelf'
    )


def _item_in(
    db_session: Session,
    org: Organization,
    location: StorageLocation,
    symbol: str,
    *,
    name: str,
) -> Item:
    uom = ModuleTestHelper(db_session).get_uom(symbol)
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=location.id,
        uom_id=uom.id,
        quantity=Decimal('10'),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _set_quantity(
    client: TestClient, headers: dict[str, str], item_id: Any, quantity: str
) -> Any:
    return client.patch(
        f'/api/v1/items/{item_id}/quantity',
        headers=headers,
        json={'quantity': quantity},
    )


class TestTheQuantityEndpointAsksTheUnit:
    def test_half_a_piece_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_location: StorageLocation,
    ) -> None:
        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Chairs')
        resp = _set_quantity(client, prec_headers, item.id, '2.5')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'pcs' in resp.text

        db_session.expire_all()
        db_session.refresh(item)
        assert item.quantity == Decimal('10')

    def test_a_whole_number_of_pieces_goes_through(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_location: StorageLocation,
    ) -> None:
        """The control: the rule is about halves, not about pieces."""
        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Tables')
        resp = _set_quantity(client, prec_headers, item.id, '3')
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def test_a_unit_that_allows_decimals_still_does(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_location: StorageLocation,
    ) -> None:
        """The control: grams go down to a thousandth, as they always did."""
        item = _item_in(db_session, prec_org, prec_location, 'g', name='Saffron')
        resp = _set_quantity(client, prec_headers, item.id, '2.5')
        assert resp.status_code == status.HTTP_200_OK, resp.text


class TestACountAsksTheUnitToo:
    def test_counting_half_a_piece_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_user: User,
        prec_location: StorageLocation,
    ) -> None:
        from app.modules.stock_takes.models import (
            StockTake,
            StockTakeItem,
            StockTakeStatus,
        )

        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Crates')
        take = StockTake(
            user_id=prec_user.id,
            organization_id=prec_org.id,
            storage_location_id=prec_location.id,
            name='Precision count',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(take)
        db_session.flush()
        row = StockTakeItem(
            stock_take_id=take.id,
            item_id=item.id,
            item_name=item.name,
            uom_id=item.uom_id,
            system_quantity=Decimal('10'),
        )
        db_session.add(row)
        db_session.commit()

        resp = client.patch(
            f'/api/v1/stock-takes/{take.id}/items/{row.id}/count',
            headers=prec_headers,
            json={'counted_quantity': '2.5'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

        db_session.expire_all()
        db_session.refresh(row)
        assert row.counted_quantity is None

    def test_counting_whole_pieces_goes_through(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_user: User,
        prec_location: StorageLocation,
    ) -> None:
        """The control."""
        from app.modules.stock_takes.models import (
            StockTake,
            StockTakeItem,
            StockTakeStatus,
        )

        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Pallets')
        take = StockTake(
            user_id=prec_user.id,
            organization_id=prec_org.id,
            storage_location_id=prec_location.id,
            name='Precision count 2',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(take)
        db_session.flush()
        row = StockTakeItem(
            stock_take_id=take.id,
            item_id=item.id,
            item_name=item.name,
            uom_id=item.uom_id,
            system_quantity=Decimal('10'),
        )
        db_session.add(row)
        db_session.commit()

        resp = client.patch(
            f'/api/v1/stock-takes/{take.id}/items/{row.id}/count',
            headers=prec_headers,
            json={'counted_quantity': '9'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text


def _use(
    client: TestClient,
    headers: dict[str, str],
    item_id: Any,
    action: str,
    quantity: str,
) -> Any:
    body: dict[str, Any] = {'quantity': quantity}
    if action == 'discard':
        body['reason'] = 'damaged'
    return client.patch(f'/api/v1/items/{item_id}/{action}', headers=headers, json=body)


class TestUsingAndDisposingAskTheUnitToo:
    """The rule had one more door left open on each side of the quantity."""

    @pytest.mark.parametrize('action', ['consume', 'discard'])
    def test_half_a_piece_cannot_leave(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_location: StorageLocation,
        action: str,
    ) -> None:
        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Lamps')
        resp = _use(client, prec_headers, item.id, action, '2.5')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'pcs' in resp.text

        db_session.expire_all()
        db_session.refresh(item)
        assert item.quantity == Decimal('10')

    @pytest.mark.parametrize('action', ['consume', 'discard'])
    def test_whole_pieces_leave(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_location: StorageLocation,
        action: str,
    ) -> None:
        """The control."""
        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Stools')
        resp = _use(client, prec_headers, item.id, action, '2')
        assert resp.status_code == status.HTTP_200_OK, resp.text


class TestASurplusAsksTheUnitToo:
    def _take(self, db_session: Session, org: Organization, user: User, location: Any):
        from app.modules.stock_takes.models import StockTake, StockTakeStatus

        take = StockTake(
            user_id=user.id,
            organization_id=org.id,
            storage_location_id=location.id,
            name='Surplus precision',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(take)
        db_session.commit()
        return take

    def test_half_a_piece_found_on_the_shelf_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_user: User,
        prec_location: StorageLocation,
    ) -> None:
        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Buckets')
        take = self._take(db_session, prec_org, prec_user, prec_location)
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/items',
            headers=prec_headers,
            json={'item_id': str(item.id), 'counted_quantity': '2.5'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_whole_pieces_found_on_the_shelf_go_through(
        self,
        client: TestClient,
        db_session: Session,
        prec_headers: dict[str, str],
        prec_org: Organization,
        prec_user: User,
        prec_location: StorageLocation,
    ) -> None:
        """The control."""
        item = _item_in(db_session, prec_org, prec_location, 'pcs', name='Mops')
        take = self._take(db_session, prec_org, prec_user, prec_location)
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/items',
            headers=prec_headers,
            json={'item_id': str(item.id), 'counted_quantity': '3'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
