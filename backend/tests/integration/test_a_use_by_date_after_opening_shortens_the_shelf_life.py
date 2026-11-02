"""A use-by date given when a package is opened shortens its shelf life.

Opening is the moment a person may say how long the opened package will keep.
The date is stored beside the opening time and never over the batch's own date;
the effective expiry is the earlier of the two, and that is the date the
expiring-soon and expired lists, the alerts and cooking's FEFO order read. Not
giving one changes nothing, and the date can be edited or cleared afterwards.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _bags(
    db: Session,
    user: User,
    shelf: StorageLocation,
    *,
    count: int,
    weight_value: Decimal | None = Decimal('2'),
    unit: str = 'pcs',
) -> Item:
    """One record of *count* units on a card that weighs 2 kg a piece."""
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name=f'Flour {uuid.uuid4().hex[:6]}',
        uom_id=_uom_id(db, unit),
        weight_value=weight_value,
        weight_uom_id=_uom_id(db, 'kg') if weight_value is not None else None,
    )
    db.add(template)
    db.flush()
    item = Item(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        storage_location_id=shelf.id,
        name=template.name,
        template_id=template.id,
        uom_id=template.uom_id,
        quantity=Decimal(count),
        expiry_date=date.today() + timedelta(days=60),
        purchase_price=Decimal('4.20'),
        currency='USD',
    )
    db.add(item)
    anchor_pending_records(db)
    db.commit()
    return item


def _use_partially(
    client: TestClient, headers: dict[str, str], item: Item, body: dict[str, Any]
) -> Any:
    return client.post(
        f'/api/v1/items/{item.id}/use-partially', json=body, headers=headers
    )


def _records(db: Session, item: Item) -> list[Item]:
    db.expire_all()
    return list(
        db.scalars(
            select(Item)
            .where(Item.template_id == item.template_id)
            .order_by(Item.created_at)
        )
    )


def _used_moves(db: Session, item: Item) -> list[Decimal]:
    return [
        move.quantity
        for move in db.scalars(
            select(StockMove).where(
                StockMove.product_template_id == item.template_id,
                StockMove.from_location_id.is_not(None),
            )
        )
    ]


def _history(db: Session, item_id: uuid.UUID) -> list[str]:
    return [
        row.action
        for row in db.scalars(
            select(ItemHistory)
            .where(ItemHistory.item_id == item_id)
            .order_by(ItemHistory.created_at)
        )
    ]


def _put_use_by(
    client: TestClient, headers: dict[str, str], item_id: Any, use_by: str | None
) -> Any:
    return client.put(
        f'/api/v1/items/{item_id}/use-by', json={'use_by': use_by}, headers=headers
    )


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


class TestAUseByAtOpening:
    def test_it_is_kept_beside_the_opening_time_and_not_over_the_batch_date(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=3)

        response = _use_partially(
            client,
            auth_headers,
            item,
            {
                'left': '1.5',
                'left_uom_id': str(_uom_id(db_session, 'kg')),
                'use_by': _day(3),
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['use_by_date'] == _day(3)
        assert body['expiry_date'] == _day(60)
        assert body['effective_expiry_date'] == _day(3)
        records = _records(db_session, item)
        opened = next(r for r in records if r.id != item.id)
        assert opened.meta_data is not None
        assert opened.meta_data['opened']['use_by'] == _day(3)
        assert opened.meta_data['opened']['at']
        sealed = next(r for r in records if r.id == item.id)
        assert not sealed.meta_data

    def test_a_date_after_the_batch_date_changes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=3)

        response = _use_partially(client, auth_headers, item, {'use_by': _day(90)})

        assert response.status_code == 200, response.text
        assert response.json()['effective_expiry_date'] == _day(60)

    def test_leaving_it_out_changes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=3)

        response = _use_partially(client, auth_headers, item, {})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['use_by_date'] is None
        assert body['effective_expiry_date'] == body['expiry_date'] == _day(60)

    def test_it_can_be_edited_and_cleared_afterwards(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=1)
        opened = _use_partially(client, auth_headers, item, {'use_by': _day(5)})
        assert opened.status_code == 200, opened.text

        edited = _put_use_by(client, auth_headers, item.id, _day(2))
        assert edited.status_code == 200, edited.text
        assert edited.json()['effective_expiry_date'] == _day(2)

        cleared = _put_use_by(client, auth_headers, item.id, None)
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()['use_by_date'] is None
        assert cleared.json()['effective_expiry_date'] == _day(60)
        assert _history(db_session, item.id).count('UPDATED') == 3
        db_session.expire_all()
        stored = db_session.get(Item, item.id)
        assert stored is not None
        assert stored.meta_data is not None
        assert 'use_by' not in stored.meta_data['opened']
        assert stored.meta_data['opened']['at']

    def test_a_sealed_record_has_no_use_by_to_set(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=3)

        response = _put_use_by(client, auth_headers, item.id, _day(2))

        assert response.status_code == 400, response.text
        assert item.name in response.text


class TestExpiryReadsTheEarlierOfTwoDates:
    def _two(
        self,
        client: TestClient,
        headers: dict[str, str],
        db: Session,
        user: User,
        shelf: StorageLocation,
    ) -> tuple[Item, Item]:
        """A sealed bag good for 60 days and an opened one with a use-by in 2."""
        sealed = _bags(db, user, shelf, count=2)
        opened = _bags(db, user, shelf, count=1)
        response = _use_partially(client, headers, opened, {'use_by': _day(2)})
        assert response.status_code == 200, response.text
        return sealed, opened

    def test_the_expiring_soon_list_carries_the_opened_pack(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        _, opened = self._two(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        listed = client.get(
            '/api/v1/items', params={'expiring_days': 7}, headers=auth_headers
        )

        assert listed.status_code == 200, listed.text
        ids = {row['id'] for row in listed.json()['items']}
        assert str(opened.id) in ids

    def test_a_use_by_in_the_past_makes_the_pack_expired_though_the_batch_is_good(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=1)
        _use_partially(client, auth_headers, item, {})
        assert _put_use_by(client, auth_headers, item.id, _day(-1)).status_code == 200

        listed = client.get(
            '/api/v1/items', params={'only_expired': True}, headers=auth_headers
        )

        assert listed.status_code == 200, listed.text
        assert str(item.id) in {row['id'] for row in listed.json()['items']}

    def test_the_alert_is_raised_for_the_use_by_not_the_batch_date(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=1)
        opened = _use_partially(client, auth_headers, item, {'use_by': _day(2)})
        assert opened.status_code == 200, opened.text

        response = client.get('/api/v1/stats/smart-alerts', headers=auth_headers)

        assert response.status_code == 200, response.text
        raised = [
            a for a in response.json()['alerts'] if a.get('item_id') == str(item.id)
        ]
        assert len(raised) == 1
        assert raised[0]['days_until_expiry'] == 2
