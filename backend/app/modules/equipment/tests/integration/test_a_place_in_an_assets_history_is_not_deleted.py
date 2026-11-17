"""A place an asset was ever checked out to cannot be deleted.

The assignment's foreign key to the place is ``ON DELETE SET NULL``, so a
delete after the return silently rewrote the asset's timeline: the past
checkout kept its dates and its holder line went blank, the place its card
named gone. A stock move is protected from exactly this by the movement guard;
the assignment is the asset's own history, and the place is refused the same
way, whether the checkout is still open or already closed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User

pytestmark = pytest.mark.integration


def _check_out(
    client: TestClient, headers: dict[str, str], item: Item, place: StorageLocation
) -> str:
    resp = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={'item_id': str(item.id), 'checkout_location_id': str(place.id)},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()['id'])


def _check_in(client: TestClient, headers: dict[str, str], assignment_id: str) -> None:
    client.post(
        f'/api/v1/equipment/assignments/{assignment_id}/checkin',
        headers=headers,
        json={},
    ).raise_for_status()


class TestAPlaceInAnAssetsHistoryIsNotDeleted:
    def test_a_closed_checkout_keeps_its_place(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_storage_type: StorageType,
        eq_user: User,
    ) -> None:
        place = h.create_storage_location(
            eq_org, eq_storage_type, eq_user, name='Workstations'
        )
        _check_in(
            client, eq_auth_headers, _check_out(client, eq_auth_headers, eq_item, place)
        )

        resp = client.delete(f'/api/v1/locations/{place.id}', headers=eq_auth_headers)

        assert resp.status_code == 409, resp.text
        assert resp.json()['detail']['code'] == 'STORAGE_HAS_EQUIPMENT_CHECKOUTS'
        # The place is still there, and the past checkout still names it.
        assert (
            client.get(
                f'/api/v1/locations/{place.id}', headers=eq_auth_headers
            ).status_code
            == 200
        )
        timeline = client.get(
            f'/api/v1/equipment/assets/{eq_item.id}/timeline', headers=eq_auth_headers
        )
        assert timeline.status_code == 200, timeline.text
        assert 'Workstations' in timeline.text

    def test_an_open_checkout_keeps_its_place_too(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_storage_type: StorageType,
        eq_user: User,
    ) -> None:
        place = h.create_storage_location(
            eq_org, eq_storage_type, eq_user, name='Workstations'
        )
        _check_out(client, eq_auth_headers, eq_item, place)

        resp = client.delete(f'/api/v1/locations/{place.id}', headers=eq_auth_headers)

        assert resp.status_code == 409, resp.text
        assert resp.json()['detail']['code'] == 'STORAGE_HAS_EQUIPMENT_CHECKOUTS'

    def test_a_place_no_asset_was_checked_out_to_is_deleted(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_storage_type: StorageType,
        eq_user: User,
    ) -> None:
        place = h.create_storage_location(
            eq_org, eq_storage_type, eq_user, name='Spare'
        )

        resp = client.delete(f'/api/v1/locations/{place.id}', headers=eq_auth_headers)

        assert resp.status_code in (200, 204), resp.text
