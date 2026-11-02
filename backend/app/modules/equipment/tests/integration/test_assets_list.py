"""Module-level equipment asset list endpoint.

The Core ``GET /items`` endpoint cannot filter by
``meta_data.equipment.equipment_status`` nor by open assignment, so the
Overview tile (counts open EquipmentAssignment rows) and the asset list
(client-side filter over one page of Core items) disagreed. The equipment
module now exposes ``GET /equipment/assets`` with ``status`` and
``checked_out`` filters (assignments are the source of truth for
"checked out").
"""

from __future__ import annotations

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

ASSETS_URL = '/api/v1/equipment/assets'


def _add_asset(
    db_session: Session,
    org: Organization,
    location: StorageLocation,
    category: Category,
    name: str,
    *,
    status: str = 'AVAILABLE',
) -> Item:
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': status}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _checkout(
    client: TestClient,
    headers: dict[str, str],
    item_id: str,
    name: str = 'Alice',
) -> str:
    resp = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={'item_id': item_id, 'assigned_to_name': name},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()['id'])


@pytest.mark.integration
class TestEquipmentAssetsEndpoint:
    """server-side status/checked-out filters for the asset list."""

    def test_list_assets_excludes_items_that_are_not_equipment(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Laptop A')
        other_cat = Category(
            name='Produce',
            code='PRODUCE',
            context_tag=None,
            organization_id=None,
        )
        db_session.add(other_cat)
        db_session.commit()
        db_session.refresh(other_cat)
        # Neither marker: a plain grocery item, not something this module wrote.
        db_session.add(
            Item(
                name='Banana',
                organization_id=eq_org.id,
                storage_location_id=eq_storage_location.id,
                category_id=other_cat.id,
                quantity=1,
            )
        )
        db_session.commit()

        resp = client.get(ASSETS_URL, headers=eq_auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        names = [i['name'] for i in body['items']]
        assert names == ['Laptop A']
        assert body['total'] == 1

    def test_asset_without_a_category_is_still_listed(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
    ) -> None:
        """The form does not force a category, so the list must not require one.

        An asset saved without one existed in the database, answered on its own
        detail route, and appeared nowhere in the module that created it.
        """
        db_session.add(
            Item(
                name='Uncategorised drill',
                organization_id=eq_org.id,
                storage_location_id=eq_storage_location.id,
                quantity=1,
                meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
            )
        )
        db_session.commit()

        resp = client.get(ASSETS_URL, headers=eq_auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [i['name'] for i in body['items']] == ['Uncategorised drill']
        assert body['total'] == 1

    def test_category_tagged_asset_without_the_namespace_is_listed(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        db_session.add(
            Item(
                name='Filed as equipment',
                organization_id=eq_org.id,
                storage_location_id=eq_storage_location.id,
                category_id=eq_category.id,
                quantity=1,
            )
        )
        db_session.commit()

        resp = client.get(ASSETS_URL, headers=eq_auth_headers)
        assert resp.status_code == 200, resp.text
        assert [i['name'] for i in resp.json()['items']] == ['Filed as equipment']

    def test_status_filter_matches_meta_data_equipment_status(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Laptop A')
        maint = _add_asset(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            'Printer B',
            status='MAINTENANCE',
        )

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'status': 'MAINTENANCE'},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == 1
        assert [i['id'] for i in body['items']] == [str(maint.id)]

        # Unknown status → empty, not an error.
        resp = client.get(
            ASSETS_URL, headers=eq_auth_headers, params={'status': 'BOGUS'}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['total'] == 0

    def test_checked_out_filter_returns_open_assignments_only(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        a = _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Laptop A')
        b = _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Laptop B')
        _checkout(client, eq_auth_headers, str(a.id))

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'checked_out': 'true'},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == 1
        assert [i['id'] for i in body['items']] == [str(a.id)]

        # After check-in the asset leaves the checked-out view.
        assignment_id = _checkout(client, eq_auth_headers, str(b.id))
        resp = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={},
        )
        assert resp.status_code == 200, resp.text
        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'checked_out': 'true'},
        )
        body = resp.json()
        ids = {i['id'] for i in body['items']}
        assert str(b.id) not in ids

    def test_checked_out_total_matches_dashboard_active_assignments(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """tile count and list count must agree."""
        for name in ('Laptop A', 'Laptop B', 'Laptop C'):
            item = _add_asset(
                db_session, eq_org, eq_storage_location, eq_category, name
            )
            _checkout(client, eq_auth_headers, str(item.id))

        dash = client.get('/api/v1/equipment/dashboard', headers=eq_auth_headers)
        assert dash.status_code == 200, dash.text
        active = dash.json()['active_assignments']

        listed = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'checked_out': 'true', 'limit': 50},
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()['total'] == active == 3

    def test_search_matches_serial_number_and_asset_tag_from_meta_data(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """The list search must reach the equipment
        serial number and asset tag stored in ``meta_data.equipment`` —
        the most common lookup in this domain (sticker on the device)."""
        macbook = _add_asset(
            db_session, eq_org, eq_storage_location, eq_category, 'MacBook Pro'
        )
        macbook.meta_data = {
            'equipment': {
                'equipment_status': 'AVAILABLE',
                'serial_number': 'C02XY1234ABC',
                'asset_tag': 'INV-0042',
            }
        }
        db_session.add(macbook)
        db_session.commit()
        _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'ThinkPad')

        # Full serial number.
        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'search': 'C02XY1234ABC'},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == 1
        assert body['items'][0]['name'] == 'MacBook Pro'

        # Fragment of the serial number.
        resp = client.get(
            ASSETS_URL, headers=eq_auth_headers, params={'search': 'XY1234'}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['total'] == 1

        # Asset tag.
        resp = client.get(
            ASSETS_URL, headers=eq_auth_headers, params={'search': 'INV-0042'}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['total'] == 1

    def test_search_matches_core_serial_number_column(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """``items.serial_number`` is filled by other
        paths and must be searchable too."""
        dell = _add_asset(
            db_session, eq_org, eq_storage_location, eq_category, 'Dell 5540'
        )
        dell.serial_number = 'DELL-SN-99'
        db_session.add(dell)
        db_session.commit()

        resp = client.get(
            ASSETS_URL, headers=eq_auth_headers, params={'search': 'DELL-SN-99'}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == 1
        assert body['items'][0]['name'] == 'Dell 5540'

    def test_other_org_items_are_excluded(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        eq_storage_type: StorageType,
    ) -> None:
        other_org = h.create_org(
            'Other Org', ['core', 'items', 'locations', 'categories']
        )
        other_user = h.create_user(other_org, email='other@example.com')
        other_loc = h.create_storage_location(
            other_org, eq_storage_type, other_user, name='Other Room'
        )
        _add_asset(
            db_session,
            other_org,
            other_loc,
            eq_category,
            'Secret Laptop',
        )

        resp = client.get(ASSETS_URL, headers=eq_auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()['total'] == 0

    def test_sort_by_name_and_direction(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """?sort=name honours sort_dir in both directions."""
        for name in ('Zebra', 'Alpha', 'Mike'):
            _add_asset(db_session, eq_org, eq_storage_location, eq_category, name)

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'sort': 'name', 'sort_dir': 'asc'},
        )
        assert resp.status_code == 200, resp.text
        assert [i['name'] for i in resp.json()['items']] == ['Alpha', 'Mike', 'Zebra']

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'sort': 'name', 'sort_dir': 'desc'},
        )
        assert resp.status_code == 200, resp.text
        assert [i['name'] for i in resp.json()['items']] == ['Zebra', 'Mike', 'Alpha']

    def test_sort_by_warranty_until_nulls_last(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """warranty sort reads meta_data.equipment.warranty_until and
        keeps assets without a warranty at the end regardless of direction."""
        no_warranty = _add_asset(
            db_session, eq_org, eq_storage_location, eq_category, 'No Warranty'
        )
        no_warranty.meta_data = {'equipment': {'equipment_status': 'AVAILABLE'}}
        soon = _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Soon')
        soon.meta_data = {
            'equipment': {
                'equipment_status': 'AVAILABLE',
                'warranty_until': '2026-12-31',
            }
        }
        late = _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Late')
        late.meta_data = {
            'equipment': {
                'equipment_status': 'AVAILABLE',
                'warranty_until': '2028-06-01',
            }
        }
        db_session.add_all([no_warranty, soon, late])
        db_session.commit()

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'sort': 'warranty_until', 'sort_dir': 'asc'},
        )
        assert resp.status_code == 200, resp.text
        assert [i['name'] for i in resp.json()['items']] == [
            'Soon',
            'Late',
            'No Warranty',
        ]

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'sort': 'warranty_until', 'sort_dir': 'desc'},
        )
        assert resp.status_code == 200, resp.text
        assert [i['name'] for i in resp.json()['items']] == [
            'Late',
            'Soon',
            'No Warranty',
        ]

    def test_sort_by_location_name(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        eq_storage_type: StorageType,
        h: ModuleTestHelper,
        eq_user: User,
    ) -> None:
        """?sort=location orders by the storage location name."""
        second_loc = h.create_storage_location(
            eq_org, eq_storage_type, eq_user, name='Annex B'
        )
        _add_asset(db_session, eq_org, second_loc, eq_category, 'In Annex')
        _add_asset(
            db_session, eq_org, eq_storage_location, eq_category, 'In Server Room'
        )

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'sort': 'location', 'sort_dir': 'asc'},
        )
        assert resp.status_code == 200, resp.text
        assert [i['name'] for i in resp.json()['items']] == [
            'In Annex',
            'In Server Room',
        ]

    def test_list_includes_location_name_and_open_holder(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """the list payload carries storage_location_name and the open
        assignment's holder for the table columns."""
        asset = _add_asset(
            db_session, eq_org, eq_storage_location, eq_category, 'Checked Out'
        )
        _checkout(client, eq_auth_headers, str(asset.id), name='Alice Nowak')

        resp = client.get(ASSETS_URL, headers=eq_auth_headers)
        assert resp.status_code == 200, resp.text
        item = resp.json()['items'][0]
        assert item['name'] == 'Checked Out'
        assert item['location_name'] == 'Server Room A'
        assert item['holder_name'] == 'Alice Nowak'
        assert item['holder_kind'] == 'person'

    def test_list_names_the_place_a_deployment_stands_in(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """A deployment has no person to name; the list still answers
        "who or what holds it" with the place, and says which of the two."""
        asset = _add_asset(
            db_session, eq_org, eq_storage_location, eq_category, 'In The Rack'
        )
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(asset.id),
                'assigned_to_name': '',
                'checkout_location_id': str(eq_storage_location.id),
            },
        )
        assert resp.status_code == 201, resp.text

        listing = client.get(ASSETS_URL, headers=eq_auth_headers)
        assert listing.status_code == 200, listing.text
        item = listing.json()['items'][0]
        assert item['name'] == 'In The Rack'
        assert item['holder_name'] == 'Server Room A'
        assert item['holder_kind'] == 'location'

    def test_search_and_pagination_envelope(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        for i in range(3):
            _add_asset(
                db_session,
                eq_org,
                eq_storage_location,
                eq_category,
                f'Router {i}',
            )

        resp = client.get(
            ASSETS_URL, headers=eq_auth_headers, params={'search': 'router'}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == 3
        assert body['limit'] == 50
        assert body['offset'] == 0
        assert body['has_more'] is False

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'search': 'router', 'limit': 2, 'offset': 0},
        )
        body = resp.json()
        assert body['total'] == 3
        assert len(body['items']) == 2
        assert body['has_more'] is True

        resp = client.get(
            ASSETS_URL,
            headers=eq_auth_headers,
            params={'search': 'router', 'limit': 2, 'offset': 2},
        )
        body = resp.json()
        assert body['total'] == 3
        assert len(body['items']) == 1
        assert body['has_more'] is False
