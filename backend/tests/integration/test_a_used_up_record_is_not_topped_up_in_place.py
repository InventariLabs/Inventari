"""A used-up record is not topped up where it stands.

Using the last unit up files the record under the virtual Consumed location,
where stock is not counted. The row's "+1 unit" sent the stored figure plus
one through the quantity door, so the unit landed in that virtual place: a
record with a positive quantity that no list, search or counter would show,
visible on its own card alone. The door refuses the raise and says where the
record stands and what to do first; lowering a quantity there, or any change
on a real shelf, goes through as before.

The assertions read the stored record, not only the status: with the guard
removed the PATCH answers 200 and the record keeps the unit.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.item import Item
from app.models.storage_location import LocationUsage, StorageLocation

pytestmark = pytest.mark.integration

POLISH = {'Accept-Language': 'pl'}


def _used_up(client, auth_headers, shelf) -> str:
    created = client.post(
        '/api/v1/items',
        headers=auth_headers,
        json={
            'name': 'Last slice',
            'location_id': str(shelf.id),
            'quantity': 1,
        },
    )
    assert created.status_code == 201, created.text
    item_id = created.json()['id']
    consumed = client.patch(
        f'/api/v1/items/{item_id}/consume',
        headers=auth_headers,
        json={'quantity': 1, 'reason': 'eaten'},
    )
    assert consumed.status_code == 200, consumed.text
    return item_id


def _consumed_place(db_session) -> StorageLocation:
    return db_session.scalars(
        select(StorageLocation).where(StorageLocation.usage == LocationUsage.CUSTOMER)
    ).one()


def _stored(db_session, item_id):
    db_session.expire_all()
    item = db_session.scalars(select(Item).where(Item.id == item_id)).one()
    place = db_session.scalars(
        select(StorageLocation).where(StorageLocation.id == item.storage_location_id)
    ).one()
    return item, place


class TestAUsedUpRecordIsNotToppedUpInPlace:
    def test_the_raise_is_refused_and_names_the_place(
        self, client, auth_headers, test_storage_location, db_session
    ):
        item_id = _used_up(client, auth_headers, test_storage_location)

        response = client.patch(
            f'/api/v1/items/{item_id}/quantity',
            headers=auth_headers,
            json={'quantity': 1},
        )

        assert response.status_code == 400, response.text
        item, place = _stored(db_session, item_id)
        assert place.usage == LocationUsage.CUSTOMER
        assert 'Consumed' in response.text
        assert item.quantity == 0, 'the refused unit must not reach the record'

    def test_the_refusal_speaks_the_readers_language(
        self, client, auth_headers, test_storage_location
    ):
        item_id = _used_up(client, auth_headers, test_storage_location)

        response = client.patch(
            f'/api/v1/items/{item_id}/quantity',
            headers={**auth_headers, **POLISH},
            json={'quantity': 1},
        )

        assert response.status_code == 400, response.text
        assert 'przenieś' in response.json()['detail']['message']

    def test_lowering_in_a_virtual_place_still_goes_through(
        self, client, auth_headers, test_storage_location, db_session
    ):
        # A record can stand in a virtual place with a quantity of its own —
        # booked there by a correction, not by this door. The guard is about
        # raising stock where it is not counted; taking it down stays open.
        # The virtual places are seeded by the first consumption (lazily), so
        # one throwaway record going used-up stands the place up first.
        _used_up(client, auth_headers, test_storage_location)
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Written off',
                'location_id': str(test_storage_location.id),
                'quantity': 2,
            },
        )
        assert created.status_code == 201, created.text
        item_id = created.json()['id']
        moved = client.patch(
            f'/api/v1/items/{item_id}/move',
            headers=auth_headers,
            json={'to_location_id': str(_consumed_place(db_session).id)},
        )
        assert moved.status_code == 200, moved.text

        response = client.patch(
            f'/api/v1/items/{item_id}/quantity',
            headers=auth_headers,
            json={'quantity': 1},
        )

        assert response.status_code == 200, response.text
        item, _place = _stored(db_session, item_id)
        assert item.quantity == 1

    def test_a_record_on_a_shelf_still_takes_the_raise(
        self, client, auth_headers, test_storage_location
    ):
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'On the shelf',
                'location_id': str(test_storage_location.id),
                'quantity': 2,
            },
        )
        assert created.status_code == 201, created.text

        response = client.patch(
            f'/api/v1/items/{created.json()["id"]}/quantity',
            headers=auth_headers,
            json={'quantity': 3},
        )

        assert response.status_code == 200, response.text
