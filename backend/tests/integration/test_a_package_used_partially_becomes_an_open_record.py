"""Using a package partially opens one unit as a record of its own.

Three 2 kg bags sit on a shelf as one record. Somebody opens one and says
1.5 kg is left. The record becomes two sealed bags and, beside them, one open
record of 0.75 of a piece with the time it was opened; the 0.25 that went is
an ordinary USED movement. The person says what is LEFT, so saying it twice
takes nothing off the second time.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
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
        expiry_date=date(2027, 1, 31),
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


class TestUsePartially:
    def test_the_opened_packages_consumption_names_its_owner_and_batch(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=2)
        owner = Partner(
            organization_id=test_user.organization_id, name='Owner', type='CUSTOMER'
        )
        lot = StockLot(
            organization_id=test_user.organization_id,
            product_template_id=item.template_id,
            name='OPENED-BATCH',
        )
        db_session.add_all([owner, lot])
        db_session.flush()
        item.owner_id, item.lot_id = owner.id, lot.id
        db_session.commit()

        response = _use_partially(
            client,
            auth_headers,
            item,
            {'left': '1.5', 'left_uom_id': str(_uom_id(db_session, 'kg'))},
        )

        assert response.status_code == 200, response.text
        move = db_session.scalars(
            select(StockMove).where(
                StockMove.product_template_id == item.template_id,
                StockMove.from_location_id.is_not(None),
            )
        ).one()
        assert (move.owner_id, move.lot_id, move.quantity) == (
            owner.id,
            lot.id,
            Decimal('0.25'),
        )

    def test_one_bag_of_three_is_opened_and_what_is_left_is_stated(
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
            {'left': '1.5', 'left_uom_id': str(_uom_id(db_session, 'kg'))},
        )

        assert response.status_code == 200, response.text
        records = _records(db_session, item)
        sealed = next(r for r in records if r.id == item.id)
        opened = next(r for r in records if r.id != item.id)
        assert sealed.quantity == Decimal('2')
        assert opened.quantity == Decimal('0.75')
        assert opened.meta_data['opened']['at']
        # The opened bag is the same goods as the ones beside it.
        assert opened.expiry_date == date(2027, 1, 31)
        assert opened.purchase_price == Decimal('4.20')
        assert opened.template_id == item.template_id
        assert opened.storage_location_id == item.storage_location_id
        assert response.json()['id'] == str(opened.id)
        # Nothing but the use moved: 3 became 2 + 0.75, and 0.25 went.
        assert sum(r.quantity for r in records) == Decimal('2.75')
        assert Decimal('0.25') in _used_moves(db_session, item)
        assert 'OPENED' in _history(db_session, opened.id)
        assert 'USED' in _history(db_session, opened.id)
        # The record that was scanned lost a unit, and its own history says so.
        assert 'QUANTITY_CHANGED' in _history(db_session, item.id)
        details = db_session.scalar(
            select(ItemHistory.changes).where(
                ItemHistory.item_id == opened.id, ItemHistory.action == 'OPENED'
            )
        )
        assert details['left'] == 1.5
        assert details['left_unit'] == 'kg'

    def test_saying_the_same_amount_twice_takes_nothing_the_second_time(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=3)
        body = {'left': '1.5', 'left_uom_id': str(_uom_id(db_session, 'kg'))}
        first = _use_partially(client, auth_headers, item, body)
        opened_id = first.json()['id']

        second = client.post(
            f'/api/v1/items/{opened_id}/use-partially', json=body, headers=auth_headers
        )

        assert second.status_code == 200, second.text
        records = _records(db_session, item)
        assert sum(r.quantity for r in records) == Decimal('2.75')
        assert len(_used_moves(db_session, item)) == 1

    def test_opening_without_an_amount_splits_and_flags_and_moves_no_stock(
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
        records = _records(db_session, item)
        assert sorted(r.quantity for r in records) == [Decimal('1'), Decimal('2')]
        assert _used_moves(db_session, item) == []

    def test_a_single_unit_is_flagged_where_it_stands(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=1)

        response = _use_partially(
            client,
            auth_headers,
            item,
            {'left': '0.5'},
        )

        assert response.status_code == 200, response.text
        records = _records(db_session, item)
        assert len(records) == 1
        assert records[0].id == item.id
        assert records[0].quantity == Decimal('0.5')
        assert records[0].meta_data['opened']['at']

    def test_finished_uses_up_the_opened_unit_and_leaves_the_sealed_ones(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(db_session, test_user, test_storage_location, count=3)

        response = _use_partially(client, auth_headers, item, {'left': '0'})

        assert response.status_code == 200, response.text
        records = _records(db_session, item)
        assert next(r for r in records if r.id == item.id).quantity == Decimal('2')
        assert Decimal('1') in _used_moves(db_session, item)

    def test_more_than_one_unit_left_is_refused_by_name(
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
            {'left': '3', 'left_uom_id': str(_uom_id(db_session, 'kg'))},
        )

        assert response.status_code == 400, response.text
        assert [r.quantity for r in _records(db_session, item)] == [Decimal('3')]

    def test_a_card_that_does_not_say_what_a_piece_weighs_cannot_be_measured(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _bags(
            db_session, test_user, test_storage_location, count=3, weight_value=None
        )

        response = _use_partially(
            client,
            auth_headers,
            item,
            {'left': '1.5', 'left_uom_id': str(_uom_id(db_session, 'kg'))},
        )

        assert response.status_code == 400, response.text
        assert [r.quantity for r in _records(db_session, item)] == [Decimal('3')]
        # It can still be opened and finished.
        opened = _use_partially(client, auth_headers, item, {})
        assert opened.status_code == 200, opened.text
