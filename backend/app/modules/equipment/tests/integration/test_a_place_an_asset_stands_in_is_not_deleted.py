"""A place an asset is checked out to is not deleted out from under it.

An asset checked out to a place that is not its home stands in that place:
the asset list says so, the place's row counts it, and a filter by the place
finds it. The delete guard read the home column alone, so the place was
offered with an enabled delete button and answered 204 — the open assignment
was left naming a row that no longer existed, and the asset fell back to its
home. The guard now counts every record that names the place, the home a
record belongs to or the place it is checked out to, and both doors into a
delete refuse it until the asset comes back.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.i18n.service import get_error_message
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User


@pytest.fixture
def workstations(
    h: ModuleTestHelper,
    eq_org: Organization,
    eq_storage_type: StorageType,
    eq_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        eq_org, eq_storage_type, eq_user, name='Workstations'
    )


def _place(
    client: TestClient, headers: dict[str, str], item: Item, place: StorageLocation
) -> str:
    resp = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={'item_id': str(item.id), 'checkout_location_id': str(place.id)},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()['id'])


def _still_there(db_session: Session, place_id: UUID) -> bool:
    # Read the row, not the instance: a deleted row leaves its cached object
    # behind and refreshing it raises.
    db_session.expunge_all()
    return (
        db_session.scalar(
            select(StorageLocation.id).where(StorageLocation.id == place_id)
        )
        is not None
    )


def _location_rows(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(
        '/api/v1/locations?module_scope=equipment&counts=true', headers=headers
    )
    assert resp.status_code == 200, resp.text
    return {row['name']: row for row in resp.json()['items']}


def test_delete_refuses_a_place_an_asset_is_checked_out_to(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_item: Item,
    workstations: StorageLocation,
    db_session: Session,
) -> None:
    _place(client, eq_auth_headers, eq_item, workstations)
    place_id = workstations.id
    item_id = eq_item.id

    response = client.delete(f'/api/v1/locations/{place_id}', headers=eq_auth_headers)

    assert response.status_code == 400, response.text
    assert response.json()['detail']['code'] == 'STORAGE_DELETE_FAILED_ITEMS'
    assert _still_there(db_session, place_id)
    # The assignment still stands in the place it was given: the refusal left
    # the checkout as it was.
    row = next(
        r
        for r in client.get('/api/v1/equipment/assets', headers=eq_auth_headers).json()[
            'items'
        ]
        if r['id'] == str(item_id)
    )
    assert row['location_id'] == str(place_id)


def test_reorg_refuses_to_delete_a_place_an_asset_is_checked_out_to(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_item: Item,
    workstations: StorageLocation,
    db_session: Session,
) -> None:
    _place(client, eq_auth_headers, eq_item, workstations)
    place_id = workstations.id

    response = client.post(
        '/api/v1/locations/reorg',
        headers=eq_auth_headers,
        json={'operations': [{'op': 'delete', 'id': str(place_id)}]},
    )

    body = response.json()
    assert body['applied'] is False, body
    assert [r['reason'] for r in body['rejections']] == [
        get_error_message('storage_delete_failed_items', 'en'),
    ]
    assert _still_there(db_session, place_id)


def test_the_row_that_carries_the_count_refuses_the_delete(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_item: Item,
    eq_storage_location: StorageLocation,
    workstations: StorageLocation,
) -> None:
    # The screen disables Delete on `total_items_count`; it has to count the
    # place the asset stands in, or the button stays enabled over a refusal.
    _place(client, eq_auth_headers, eq_item, workstations)

    rows = _location_rows(client, eq_auth_headers)

    assert rows['Workstations']['total_items_count'] == 1
    # The home still holds the record it owns, so it stays refused as well.
    assert rows[eq_storage_location.name]['total_items_count'] == 1


def test_the_place_can_be_deleted_once_the_asset_comes_back(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_item: Item,
    workstations: StorageLocation,
    db_session: Session,
) -> None:
    assignment_id = _place(client, eq_auth_headers, eq_item, workstations)
    place_id = workstations.id
    client.post(
        f'/api/v1/equipment/assignments/{assignment_id}/checkin',
        headers=eq_auth_headers,
        json={},
    ).raise_for_status()

    response = client.delete(f'/api/v1/locations/{place_id}', headers=eq_auth_headers)

    assert response.status_code == 204, response.text
    assert not _still_there(db_session, place_id)
