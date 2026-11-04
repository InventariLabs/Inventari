"""Closing a shelf: what nobody found on it is counted as none.

A warehouse count is walked shelf by shelf, and the counter closes each one
when done. Whatever the shelf was expected to hold and nobody scanned is
then counted as zero — a shortage, not a row left waiting — and a shelf
found empty is confirmed as empty, which is a result of the count too: the
report says which shelves were closed, and by whom.

A shelf nobody closed is left as it was: its rows wait to be counted, so a
count that asks for every row still refuses to close over them, and a
partial count leaves their stock alone.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


@pytest.fixture
def org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Shelf Close Org',
        ['core', 'items', 'locations', 'categories', 'stock_takes', 'stats'],
    )


@pytest.fixture
def user(db_session: Session, org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        org, email='shelf-closer@example.com'
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
        f'Rack {name}',
        f'CLOSE_{name.upper().replace(" ", "_")}',
        organization_id=org.id,
    )
    location = h.create_storage_location(org, storage_type, user, name=name)
    if parent is not None:
        location.parent_id = parent.id
        db_session.commit()
        db_session.refresh(location)
    return location


@pytest.fixture
def rack(db_session: Session, org: Organization, user: User) -> StorageLocation:
    return _location(db_session, org, user, 'Rack C')


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
def flour(db_session: Session, org: Organization) -> ProductTemplate:
    return ModuleTestHelper(db_session).create_template(org, name='Flour')


@pytest.fixture
def sugar(db_session: Session, org: Organization) -> ProductTemplate:
    return ModuleTestHelper(db_session).create_template(org, name='Sugar')


def _open_count(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    *,
    require_full_count: bool = False,
    blind_mode: bool = False,
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/stock-takes',
        headers=headers,
        json={
            'name': 'Rack C by shelf',
            'location_id': str(location.id),
            'require_full_count': require_full_count,
            'blind_mode': blind_mode,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    detail = client.get(f'/api/v1/stock-takes/{created.json()["id"]}', headers=headers)
    assert detail.status_code == status.HTTP_200_OK, detail.text
    body: dict[str, Any] = detail.json()
    return body


def _row_of(count: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in count['items'] if row['item_id'] == record['id'])


def _count(
    client: TestClient,
    headers: dict[str, str],
    count: dict[str, Any],
    row: dict[str, Any],
    quantity: str,
) -> None:
    response = client.patch(
        f'/api/v1/stock-takes/{count["id"]}/items/{row["id"]}/count',
        headers=headers,
        json={'counted_quantity': quantity},
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _close(
    client: TestClient,
    headers: dict[str, str],
    count: dict[str, Any],
    shelf: StorageLocation,
) -> Any:
    return client.post(
        f'/api/v1/stock-takes/{count["id"]}/locations/{shelf.id}/close',
        headers=headers,
    )


def _complete(
    client: TestClient, headers: dict[str, str], count: dict[str, Any]
) -> Any:
    return client.post(
        f'/api/v1/stock-takes/{count["id"]}/complete',
        headers=headers,
        json={'apply_adjustments': True},
    )


class TestClosingAShelf:
    def test_its_rows_nobody_counted_are_counted_as_none(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        flour: ProductTemplate,
        sugar: ProductTemplate,
    ) -> None:
        counted = post_on_shelf(client, headers, flour, shelf_one.id, 4)
        missing = post_on_shelf(client, headers, sugar, shelf_one.id, 6)
        elsewhere = post_on_shelf(client, headers, sugar, shelf_two.id, 2)
        count = _open_count(client, headers, rack)
        _count(client, headers, count, _row_of(count, counted), '3')

        response = _close(client, headers, count, shelf_one)

        assert response.status_code == status.HTTP_200_OK, response.text
        closed = response.json()
        assert closed['counted_as_zero'] == 1
        assert closed['location_id'] == str(shelf_one.id)
        assert closed['path'] == 'Rack C › Shelf 1'
        assert closed['empty'] is False
        assert closed['closed_by_name'] == 'Shelf-Closer'
        after = client.get(f'/api/v1/stock-takes/{count["id"]}', headers=headers)
        rows = {row['item_id']: row for row in after.json()['items']}
        assert Decimal(rows[counted['id']]['counted_quantity']) == Decimal('3')
        assert Decimal(rows[missing['id']]['counted_quantity']) == Decimal('0')
        assert rows[missing['id']]['is_discrepancy'] == 1
        # Who closed the shelf counted the row: the pass names them.
        assert rows[missing['id']]['counts'][0]['counted_by_name'] == 'Shelf-Closer'
        # The other shelf was not closed: its row still waits.
        assert rows[elsewhere['id']]['counted_quantity'] is None
        assert [shelf['path'] for shelf in after.json()['closed_locations']] == [
            'Rack C › Shelf 1'
        ]

    def test_the_report_shows_them_as_shortages_and_the_stock_follows(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        flour: ProductTemplate,
        sugar: ProductTemplate,
    ) -> None:
        missing = post_on_shelf(client, headers, flour, shelf_one.id, 6)
        untouched = post_on_shelf(client, headers, sugar, shelf_two.id, 2)
        count = _open_count(client, headers, rack)
        assert _close(client, headers, count, shelf_one).status_code == 200

        done = _complete(client, headers, count)

        assert done.status_code == status.HTTP_200_OK, done.text
        report = done.json()
        assert report['understock'] == 1
        assert report['not_counted'] == 1
        [shortage] = report['discrepancy_items']
        assert shortage['item_id'] == missing['id']
        assert Decimal(shortage['difference']) == Decimal('-6')
        db_session.expire_all()
        gone = db_session.get(Item, UUID(missing['id']))
        assert gone is not None and gone.quantity == Decimal('0')
        # A shelf nobody closed keeps what its record says.
        kept = db_session.get(Item, UUID(untouched['id']))
        assert kept is not None and kept.quantity == Decimal('2')

    def test_a_blind_count_is_told_how_many_rows_not_what_they_held(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        flour: ProductTemplate,
    ) -> None:
        post_on_shelf(client, headers, flour, shelf_one.id, 6)
        count = _open_count(client, headers, rack, blind_mode=True)

        response = _close(client, headers, count, shelf_one)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['counted_as_zero'] == 1
        assert 'system_quantity' not in response.text

    def test_a_shelf_outside_the_count_is_refused(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        user: User,
        rack: StorageLocation,
    ) -> None:
        elsewhere = _location(db_session, org, user, 'Other Rack')
        count = _open_count(client, headers, rack)

        response = _close(client, headers, count, elsewhere)

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert response.json()['detail']['code'] == 'STOCK_TAKE_SHELF_OUTSIDE_LOCATION'

    def test_a_closed_count_has_no_shelf_left_to_close(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
    ) -> None:
        count = _open_count(client, headers, rack)
        assert _complete(client, headers, count).status_code == 200

        response = _close(client, headers, count, shelf_one)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text


class TestAnEmptyShelf:
    def test_a_shelf_with_no_rows_is_confirmed_empty_and_reported(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        flour: ProductTemplate,
    ) -> None:
        post_on_shelf(client, headers, flour, shelf_one.id, 4)
        count = _open_count(client, headers, rack)

        response = _close(client, headers, count, shelf_two)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['empty'] is True
        assert response.json()['counted_as_zero'] == 0
        report = client.get(
            f'/api/v1/stock-takes/{count["id"]}/report', headers=headers
        )
        assert report.status_code == status.HTTP_200_OK, report.text
        [confirmed] = report.json()['closed_locations']
        assert confirmed['path'] == 'Rack C › Shelf 2'
        assert confirmed['empty'] is True
        assert confirmed['closed_by_name'] == 'Shelf-Closer'
        assert confirmed['closed_at']

    def test_a_shelf_whose_rows_all_close_at_zero_is_empty(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        flour: ProductTemplate,
        sugar: ProductTemplate,
    ) -> None:
        typed = post_on_shelf(client, headers, flour, shelf_one.id, 4)
        post_on_shelf(client, headers, sugar, shelf_one.id, 6)
        count = _open_count(client, headers, rack)
        _count(client, headers, count, _row_of(count, typed), '0')

        response = _close(client, headers, count, shelf_one)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['empty'] is True
        assert response.json()['counted_as_zero'] == 1

    def test_closing_again_restates_the_shelf_once(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
    ) -> None:
        count = _open_count(client, headers, rack)
        assert _close(client, headers, count, shelf_one).status_code == 200

        again = _close(client, headers, count, shelf_one)

        assert again.status_code == status.HTTP_200_OK, again.text
        done = _complete(client, headers, count)
        assert done.status_code == status.HTTP_200_OK, done.text
        assert len(done.json()['closed_locations']) == 1


class TestAShelfNobodyClosed:
    def test_a_full_count_still_refuses_over_its_rows(
        self,
        client: TestClient,
        headers: dict[str, str],
        rack: StorageLocation,
        shelf_one: StorageLocation,
        shelf_two: StorageLocation,
        flour: ProductTemplate,
        sugar: ProductTemplate,
    ) -> None:
        post_on_shelf(client, headers, flour, shelf_one.id, 4)
        post_on_shelf(client, headers, sugar, shelf_two.id, 2)
        count = _open_count(client, headers, rack, require_full_count=True)
        assert _close(client, headers, count, shelf_one).status_code == 200

        refused = _complete(client, headers, count)
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text

        assert _close(client, headers, count, shelf_two).status_code == 200
        done = _complete(client, headers, count)
        assert done.status_code == status.HTTP_200_OK, done.text
        assert done.json()['understock'] == 2
