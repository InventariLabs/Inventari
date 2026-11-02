"""An asset checked out to a place is shown standing in that place.

A webcam on "Server Rack B" checked out to the location "Workstations" kept
"Server Rack B" in the list's Location column while the Assigned-to column
said Workstations: "where is it" had two answers. The asset's own location is
its home and stays so in the record; while it is checked out to a place the
list reports that place, a filter by the place finds it, and the return puts
it back home — or wherever the return says it went.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.category import Category
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


def _rows(client: TestClient, headers: dict[str, str], query: str = '') -> list[Any]:
    resp = client.get(f'/api/v1/equipment/assets{query}', headers=headers)
    assert resp.status_code == 200, resp.text
    return list(resp.json()['items'])


def _row(client: TestClient, headers: dict[str, str], item: Item) -> Any:
    return next(r for r in _rows(client, headers) if r['id'] == str(item.id))


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


@pytest.mark.integration
class TestAPlacedAssetStandsWhereItWasPlaced:
    def test_the_list_names_the_place_and_the_return_brings_it_home(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
        workstations: StorageLocation,
    ) -> None:
        assignment_id = _place(client, eq_auth_headers, eq_item, workstations)

        row = _row(client, eq_auth_headers, eq_item)
        assert row['location_id'] == str(workstations.id)
        assert row['location_name'] == 'Workstations'
        assert row['holder_kind'] == 'location'
        # A filter by a place finds what the rows say stands in it, and the
        # home no longer claims the asset while it is away.
        here = _rows(client, eq_auth_headers, f'?location_id={workstations.id}')
        assert [r['id'] for r in here] == [str(eq_item.id)]
        home = _rows(client, eq_auth_headers, f'?location_id={eq_storage_location.id}')
        assert str(eq_item.id) not in [r['id'] for r in home]
        # The record keeps its home: the checkout did not move it.
        detail = client.get(f'/api/v1/items/{eq_item.id}', headers=eq_auth_headers)
        assert detail.json()['location_id'] == str(eq_storage_location.id)

        client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'return_location_id': str(eq_storage_location.id)},
        ).raise_for_status()

        row = _row(client, eq_auth_headers, eq_item)
        assert row['location_id'] == str(eq_storage_location.id)
        assert row['holder_name'] is None

    def test_a_return_that_lands_elsewhere_is_recorded_there(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        workstations: StorageLocation,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_storage_type: StorageType,
        eq_user: User,
    ) -> None:
        lab = h.create_storage_location(eq_org, eq_storage_type, eq_user, name='Lab')
        assignment_id = _place(client, eq_auth_headers, eq_item, workstations)

        client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'return_location_id': str(lab.id)},
        ).raise_for_status()

        assert _row(client, eq_auth_headers, eq_item)['location_id'] == str(lab.id)

    def test_a_bulk_return_can_send_the_batch_to_one_place(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        workstations: StorageLocation,
    ) -> None:
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Priya Raman'},
        ).raise_for_status()

        resp = client.post(
            '/api/v1/equipment/items/bulk-return',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'return_location_id': str(workstations.id),
            },
        )

        assert resp.json() == {'checked_in': 1, 'errors': []}
        assert _row(client, eq_auth_headers, eq_item)['location_id'] == str(
            workstations.id
        )

    def test_a_return_to_a_place_of_another_organization_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
        h: ModuleTestHelper,
        eq_storage_type: StorageType,
    ) -> None:
        other_org = h.create_org('Elsewhere Ltd', ['core', 'locations'])
        other_user = h.create_user(other_org, email='else@example.com')
        foreign = h.create_storage_location(
            other_org, eq_storage_type, other_user, name='Not yours'
        )
        out = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Priya Raman'},
        ).json()

        resp = client.post(
            f'/api/v1/equipment/assignments/{out["id"]}/checkin',
            headers=eq_auth_headers,
            json={'return_location_id': str(foreign.id)},
        )

        assert resp.status_code == 400, resp.text
        assert _row(client, eq_auth_headers, eq_item)['location_id'] == str(
            eq_storage_location.id
        )

    def test_sorting_by_location_reads_the_place_the_row_names(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        workstations: StorageLocation,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_storage_type: StorageType,
        eq_user: User,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        # Home "Server Room A" sorts before "Training room", the place it
        # stands in ("Workstations") after it: a sort by the home put the
        # rows out of the order their Location column reads.
        training = h.create_storage_location(
            eq_org, eq_storage_type, eq_user, name='Training room'
        )
        projector = Item(
            name='Projector',
            organization_id=eq_org.id,
            storage_location_id=training.id,
            category_id=eq_category.id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(projector)
        db_session.commit()
        _place(client, eq_auth_headers, eq_item, workstations)

        ascending = _rows(client, eq_auth_headers, '?sort=location&sort_dir=asc')
        descending = _rows(client, eq_auth_headers, '?sort=location&sort_dir=desc')

        assert [r['location_name'] for r in ascending] == [
            'Training room',
            'Workstations',
        ]
        assert [r['location_name'] for r in descending] == [
            'Workstations',
            'Training room',
        ]

    def test_the_locations_page_counts_it_where_it_stands(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
        workstations: StorageLocation,
    ) -> None:
        _place(client, eq_auth_headers, eq_item, workstations)

        resp = client.get(
            '/api/v1/locations?module_scope=equipment&counts=true',
            headers=eq_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        rows = {row['name']: row for row in resp.json()['items']}

        # "Workstations" holds no asset of its own and carries no tag: the
        # placement alone is what lists it, with the count its link opens.
        assert rows['Workstations']['items_count'] == 1
        assert rows['Workstations']['subtree_items_count'] == 1
        assert rows['Server Room A']['items_count'] == 0
        # The home keeps the record, and the delete guard answers for it.
        assert rows['Server Room A']['total_items_count'] == 1
        assert rows['Workstations']['total_items_count'] == 0
