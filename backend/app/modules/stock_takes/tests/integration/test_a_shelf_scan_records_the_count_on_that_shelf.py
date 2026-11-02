"""Counting by location: what is counted at a shelf is recorded on that shelf.

A count covers a location and everything below it, and a warehouse walks it
shelf by shelf. Every row therefore says which shelf it counts — the shelf
its record stood on when the count opened — and the counting screen is told
which shelves the count covers, so a scanned location label can be checked
against them.

Goods found on a shelf that the snapshot expected somewhere else in the tree
are recorded where they were found: a surplus row on the scanned shelf,
backed by a record of the same goods standing there, while the row where
they were expected keeps waiting for its own count. Closing the count posts
both: a shortage where the goods were expected, a surplus where they stood.

A record that is its own identity — a serial number, or no product card to
open a second record of — cannot be split that way. Its one row moves to the
shelf it was found on and remembers the shelf its record stands on; closing
the count moves the record, and the report shows the shortage on the one
shelf beside the surplus on the other.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records, post_on_shelf

pytestmark = pytest.mark.integration


@pytest.fixture
def org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Shelf Count Org',
        ['core', 'items', 'locations', 'categories', 'stock_takes', 'stats'],
    )


@pytest.fixture
def user(db_session: Session, org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        org, email='shelf-counter@example.com'
    )


@pytest.fixture
def headers(db_session: Session, user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(user)


def _location(
    db_session: Session,
    org: Organization,
    user: User,
    name: str,
    parent: StorageLocation | None = None,
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        f'Rack {name}', f'RACK_{name.upper().replace(" ", "_")}', organization_id=org.id
    )
    location = h.create_storage_location(org, storage_type, user, name=name)
    if parent is not None:
        location.parent_id = parent.id
        db_session.commit()
        db_session.refresh(location)
    return location


@pytest.fixture
def rack(db_session: Session, org: Organization, user: User) -> StorageLocation:
    return _location(db_session, org, user, 'Rack A')


@pytest.fixture
def shelf_one(
    db_session: Session, org: Organization, user: User, rack: StorageLocation
) -> StorageLocation:
    return _location(db_session, org, user, 'Shelf 1', rack)


@pytest.fixture
def shelf_two(
    db_session: Session, org: Organization, user: User, rack: StorageLocation
) -> StorageLocation:
    return _location(db_session, org, user, 'Shelf 2', rack)


@pytest.fixture
def goods(db_session: Session, org: Organization) -> ProductTemplate:
    return ModuleTestHelper(db_session).create_template(org, name='Shelf Goods')


def _open_count(
    client: TestClient, headers: dict[str, str], location: StorageLocation
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/stock-takes',
        headers=headers,
        json={
            'name': 'Rack A by shelf',
            'location_id': str(location.id),
            'require_full_count': False,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    detail = client.get(f'/api/v1/stock-takes/{created.json()["id"]}', headers=headers)
    assert detail.status_code == status.HTTP_200_OK, detail.text
    body: dict[str, Any] = detail.json()
    return body


def _found_on(
    client: TestClient,
    headers: dict[str, str],
    stock_take_id: str,
    record_id: str,
    shelf: StorageLocation,
    quantity: str = '1',
) -> Any:
    return client.post(
        f'/api/v1/stock-takes/{stock_take_id}/items',
        headers=headers,
        json={
            'item_id': record_id,
            'counted_quantity': quantity,
            'location_id': str(shelf.id),
        },
    )


class TestEveryRowKnowsItsShelf:
    def test_a_snapshot_row_carries_the_shelf_its_record_stood_on(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        record = post_on_shelf(client, headers, goods, shelf_one.id, 4)

        count = _open_count(client, headers, rack)

        [row] = count['items']
        assert row['item_id'] == record['id']
        assert row['location_id'] == str(shelf_one.id)

    def test_the_count_names_every_location_it_covers_with_its_path(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
    ) -> None:
        count = _open_count(client, headers, rack)

        covered = {row['id']: row['path'] for row in count['counted_locations']}
        assert covered == {
            str(rack.id): 'Rack A',
            str(shelf_one.id): 'Rack A / Shelf 1',
            str(shelf_two.id): 'Rack A / Shelf 2',
        }


class TestGoodsFoundOnAnotherShelf:
    def test_they_become_a_surplus_on_the_shelf_they_were_found_on(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        record = post_on_shelf(client, headers, goods, shelf_one.id, 5)
        count = _open_count(client, headers, rack)

        response = _found_on(client, headers, count['id'], record['id'], shelf_two)

        assert response.status_code == status.HTTP_201_CREATED, response.text
        row = response.json()
        assert row['location_id'] == str(shelf_two.id)
        assert row['shelf_location'] == 'Rack A / Shelf 2'
        assert Decimal(row['system_quantity']) == Decimal('0')
        assert Decimal(row['counted_quantity']) == Decimal('1')
        # Backed by a record of the same goods standing on the shelf they
        # were found on — the expected record stays where it was.
        assert row['item_id'] != record['id']
        db_session.expire_all()
        found = db_session.get(Item, UUID(row['item_id']))
        assert found is not None
        assert found.storage_location_id == shelf_two.id
        assert found.template_id == goods.id
        assert found.quantity == Decimal('0')
        expected = db_session.get(Item, UUID(record['id']))
        assert expected is not None
        assert expected.storage_location_id == shelf_one.id
        assert expected.quantity == Decimal('5')

    def test_a_second_find_on_that_shelf_names_the_row_it_already_has(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        record = post_on_shelf(client, headers, goods, shelf_one.id, 5)
        count = _open_count(client, headers, rack)
        first = _found_on(client, headers, count['id'], record['id'], shelf_two)
        assert first.status_code == status.HTTP_201_CREATED, first.text

        again = _found_on(client, headers, count['id'], record['id'], shelf_two)

        assert again.status_code == status.HTTP_409_CONFLICT, again.text
        details = again.json()['detail']
        assert details['stock_take_item_id'] == first.json()['id']
        assert details['item_id'] == first.json()['item_id']
        db_session.expire_all()
        on_shelf_two = db_session.scalars(
            select(Item).where(Item.storage_location_id == shelf_two.id)
        ).all()
        assert len(on_shelf_two) == 1

    def test_a_shelf_outside_the_count_is_refused(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        user: User,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        elsewhere = _location(db_session, org, user, 'Other Rack')
        record = post_on_shelf(client, headers, goods, shelf_one.id, 5)
        count = _open_count(client, headers, rack)

        response = _found_on(client, headers, count['id'], record['id'], elsewhere)

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert response.json()['detail']['code'] == 'STOCK_TAKE_SHELF_OUTSIDE_LOCATION'
        db_session.expire_all()
        assert (
            db_session.scalars(
                select(Item).where(Item.storage_location_id == elsewhere.id)
            ).first()
            is None
        )

    def test_closing_posts_a_shortage_where_expected_and_a_surplus_where_found(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        record = post_on_shelf(client, headers, goods, shelf_one.id, 5)
        count = _open_count(client, headers, rack)
        [expected_row] = count['items']
        found = _found_on(client, headers, count['id'], record['id'], shelf_two, '3')
        assert found.status_code == status.HTTP_201_CREATED, found.text
        nothing_left = client.patch(
            f'/api/v1/stock-takes/{count["id"]}/items/{expected_row["id"]}/count',
            headers=headers,
            json={'counted_quantity': '0'},
        )
        assert nothing_left.status_code == status.HTTP_200_OK, nothing_left.text

        done = client.post(
            f'/api/v1/stock-takes/{count["id"]}/complete',
            headers=headers,
            json={'apply_adjustments': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        report = done.json()
        assert report['overstock'] == 1
        assert report['understock'] == 1
        by_shelf = {row['location_id']: row for row in report['discrepancy_items']}
        assert Decimal(by_shelf[str(shelf_one.id)]['difference']) == Decimal('-5')
        assert Decimal(by_shelf[str(shelf_two.id)]['difference']) == Decimal('3')
        db_session.expire_all()
        expected = db_session.get(Item, UUID(record['id']))
        assert expected is not None
        assert expected.quantity == Decimal('0')
        found_record = db_session.get(Item, UUID(found.json()['item_id']))
        assert found_record is not None
        assert found_record.storage_location_id == shelf_two.id
        assert found_record.quantity == Decimal('3')

    def test_goods_already_standing_on_the_scanned_shelf_count_as_before(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        count = _open_count(client, headers, rack)
        # Put on the shelf after the snapshot: a plain surplus of that record.
        record = post_on_shelf(client, headers, goods, shelf_one.id, 2)

        response = _found_on(client, headers, count['id'], record['id'], shelf_one)

        assert response.status_code == status.HTTP_201_CREATED, response.text
        row = response.json()
        assert row['item_id'] == record['id']
        assert row['location_id'] == str(shelf_one.id)
        assert Decimal(row['system_quantity']) == Decimal('2')


def _own_identity(
    db_session: Session,
    org: Organization,
    kind: str,
    goods: ProductTemplate,
    shelf: StorageLocation,
) -> Item:
    record = Item(
        organization_id=org.id,
        name='Own Identity',
        template_id=goods.id if kind == 'serial' else None,
        serial_number='SN-SHELF-1' if kind == 'serial' else None,
        storage_location_id=shelf.id,
        quantity=Decimal('1'),
    )
    db_session.add(record)
    anchor_pending_records(db_session)
    db_session.commit()
    return record


class TestARecordThatIsItsOwnIdentity:
    """A unit with a serial number, or goods with no card, found elsewhere.

    Neither can have a second record on the shelf it was found on: the serial
    number is unique, and there is no card to open one from. Its one row
    counts the shelf it was found on and keeps the shelf its record stands
    on, so the find is not lost and the count can say both things.
    """

    @pytest.mark.parametrize('kind', ['serial', 'no_card'])
    def test_its_row_is_counted_on_the_shelf_it_was_found_on(
        self,
        kind: str,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        record = _own_identity(db_session, org, kind, goods, shelf_one)
        count = _open_count(client, headers, rack)
        [row] = count['items']

        response = _found_on(client, headers, count['id'], str(record.id), shelf_two)

        assert response.status_code == status.HTTP_201_CREATED, response.text
        found = response.json()
        assert found['id'] == row['id']
        assert found['item_id'] == str(record.id)
        assert found['location_id'] == str(shelf_two.id)
        assert found['expected_location_id'] == str(shelf_one.id)
        assert found['shelf_location'] == 'Rack A / Shelf 2'
        assert Decimal(found['counted_quantity']) == Decimal('1')
        assert found['is_discrepancy'] == 1
        again = client.get(f'/api/v1/stock-takes/{count["id"]}', headers=headers)
        assert [line['id'] for line in again.json()['items']] == [row['id']]
        # Nothing moves before the count closes.
        db_session.expire_all()
        standing = db_session.get(Item, record.id)
        assert standing is not None
        assert standing.storage_location_id == shelf_one.id

    @pytest.mark.parametrize('kind', ['serial', 'no_card'])
    def test_closing_moves_it_and_reports_a_shortage_and_a_surplus(
        self,
        kind: str,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        record = _own_identity(db_session, org, kind, goods, shelf_one)
        count = _open_count(client, headers, rack)
        found = _found_on(client, headers, count['id'], str(record.id), shelf_two)
        assert found.status_code == status.HTTP_201_CREATED, found.text

        done = client.post(
            f'/api/v1/stock-takes/{count["id"]}/complete',
            headers=headers,
            json={'apply_adjustments': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        report = done.json()
        assert report['understock'] == 1
        assert report['overstock'] == 1
        by_shelf = {row['location_id']: row for row in report['discrepancy_items']}
        assert Decimal(by_shelf[str(shelf_one.id)]['difference']) == Decimal('-1')
        assert by_shelf[str(shelf_one.id)]['shelf_location'] == 'Rack A / Shelf 1'
        assert Decimal(by_shelf[str(shelf_two.id)]['difference']) == Decimal('1')
        assert by_shelf[str(shelf_two.id)]['shelf_location'] == 'Rack A / Shelf 2'
        db_session.expire_all()
        moved = db_session.get(Item, record.id)
        assert moved is not None
        assert moved.storage_location_id == shelf_two.id
        assert moved.quantity == Decimal('1')
        assert moved.serial_number == ('SN-SHELF-1' if kind == 'serial' else None)
        # The report read back later says the same.
        later = client.get(f'/api/v1/stock-takes/{count["id"]}/report', headers=headers)
        assert later.status_code == status.HTTP_200_OK, later.text
        assert {
            row['location_id']: Decimal(row['difference'])
            for row in later.json()['discrepancy_items']
        } == {str(shelf_one.id): Decimal('-1'), str(shelf_two.id): Decimal('1')}

    def test_found_back_on_its_own_shelf_it_counts_there_again(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        goods: ProductTemplate,
    ) -> None:
        record = _own_identity(db_session, org, 'serial', goods, shelf_one)
        count = _open_count(client, headers, rack)
        away = _found_on(client, headers, count['id'], str(record.id), shelf_two)
        assert away.status_code == status.HTTP_201_CREATED, away.text

        home = _found_on(client, headers, count['id'], str(record.id), shelf_one)

        assert home.status_code == status.HTTP_201_CREATED, home.text
        row = home.json()
        assert row['id'] == away.json()['id']
        assert row['location_id'] == str(shelf_one.id)
        assert row['expected_location_id'] is None
        assert row['is_discrepancy'] == 0
        done = client.post(
            f'/api/v1/stock-takes/{count["id"]}/complete',
            headers=headers,
            json={'apply_adjustments': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        assert done.json()['discrepancy_items'] == []
        db_session.expire_all()
        standing = db_session.get(Item, record.id)
        assert standing is not None
        assert standing.storage_location_id == shelf_one.id
