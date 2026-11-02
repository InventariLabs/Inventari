"""
Integration tests for the Equipment module API.

Covers:
- POST /equipment/assignments  — checkout
- POST /equipment/assignments/{id}/checkin — checkin
- GET  /equipment/assignments  — list active
- GET  /equipment/assignments/item/{item_id} — history
- POST /equipment/maintenance  — create log
- GET  /equipment/maintenance/item/{item_id} — history
- PUT  /equipment/maintenance/{id} — update
- DELETE /equipment/maintenance/{id} — delete
- GET  /equipment/dashboard
- GET  /equipment/warranty-alerts
"""

from datetime import date, timedelta
from typing import Any, cast

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item


@pytest.mark.integration
class TestCheckout:
    """Tests for equipment check-out endpoint."""

    def test_checkout_success(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Checking out an available asset creates an assignment and updates status."""
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Jan Kowalski',
                'assigned_to_email': 'jan@example.com',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['item_id'] == str(eq_item.id)
        assert data['assigned_to_name'] == 'Jan Kowalski'
        assert data['checked_in_at'] is None

    def test_checkout_sets_deployed_status(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """After checkout, item.meta_data.equipment.equipment_status == DEPLOYED."""
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )

        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'DEPLOYED'

    def test_checkout_retired_asset_returns_409(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Checking out a RETIRED asset is forbidden."""
        from sqlalchemy.orm.attributes import flag_modified

        meta = dict(eq_item.meta_data or {})
        meta['equipment'] = {'equipment_status': 'RETIRED'}
        eq_item.meta_data = meta
        flag_modified(eq_item, 'meta_data')
        db_session.commit()

        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Bob'},
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_checkout_duplicate_returns_409(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Checking out an already checked-out asset returns 409."""
        payload = {'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'}
        client.post(
            '/api/v1/equipment/assignments', headers=eq_auth_headers, json=payload
        )

        response = client.post(
            '/api/v1/equipment/assignments', headers=eq_auth_headers, json=payload
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_checkout_requires_auth(self, client: TestClient, eq_item: Item) -> None:
        """Unauthenticated checkout returns 401."""
        response = client.post(
            '/api/v1/equipment/assignments',
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # --- ``checkout_location_id`` persistence ---------------------------

    def test_checkout_with_location_persists_field(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """When ``checkout_location_id`` is supplied it must be
        persisted on the assignment row AND returned in the response."""
        from app.core.testing import ModuleTestHelper
        from app.modules.equipment.models import EquipmentAssignment

        h = ModuleTestHelper(db_session)
        loc = h.create_storage_location(
            eq_item.organization,
            eq_item.storage_location.storage_type
            if eq_item.storage_location_id
            else h.create_storage_type('IT_RACK_B', 'IT_RACK'),
            h.create_user(eq_item.organization, email='loc-b@test.com'),
            name='Office Rack B',
        )

        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'checkout_location_id': str(loc.id),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        body = response.json()
        assert body['checkout_location_id'] == str(loc.id)
        assert body['checkout_location_name'] == 'Office Rack B'

        assignment = (
            db_session.query(EquipmentAssignment).filter_by(id=body['id']).one()
        )
        assert assignment.checkout_location_id == loc.id

    def test_checkout_without_location_persists_none(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """When ``checkout_location_id`` is omitted, the persisted value must be
        ``None`` (no error, no default)."""
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body['checkout_location_id'] is None
        assert body['checkout_location_name'] is None

    def test_checkout_with_cross_org_location_returns_400(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A ``checkout_location_id`` belonging to a different organization must
        be rejected with HTTP 400 (multi-tenancy guard, in addition to the FK)."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        other_org = h.create_org(
            'Other Equipment Org',
            ['core', 'items', 'locations', 'categories', 'equipment'],
        )
        other_user = h.create_user(other_org, email='other-loc@test.com')
        other_st = h.create_storage_type('OTHER_LOC_T', 'OTHER_LOC_T')
        other_loc = h.create_storage_location(
            other_org, other_st, other_user, name='Other Loc'
        )

        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'checkout_location_id': str(other_loc.id),
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestCheckin:
    """Tests for equipment check-in endpoint."""

    def _checkout(
        self,
        client: TestClient,
        headers: dict[str, str],
        item_id: Any,
        name: str = 'Alice',
    ) -> str:
        r = client.post(
            '/api/v1/equipment/assignments',
            headers=headers,
            json={'item_id': str(item_id), 'assigned_to_name': name},
        )
        r.raise_for_status()
        return cast(str, r.json()['id'])

    def test_checkin_success(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Checking in an active assignment sets checked_in_at."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item.id)

        response = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD', 'checkin_notes': 'All good'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['checked_in_at'] is not None
        assert data['checkin_condition'] == 'GOOD'

    def test_checkin_good_sets_available(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """GOOD condition → equipment_status = AVAILABLE."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item.id)
        client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )

        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'AVAILABLE'

    def test_checkin_damaged_sets_maintenance(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """DAMAGED condition → equipment_status = MAINTENANCE."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item.id)
        client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'DAMAGED'},
        )

        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'MAINTENANCE'

    def test_double_checkin_returns_409(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Checking in an already returned assignment returns 409."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item.id)
        client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={},
        )

        response = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={},
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    # --- Full lifecycle lease → return leaves the asset AVAILABLE -------

    def test_full_lifecycle_checkout_checkin_leaves_status_available(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A checkout → check-in with default condition must leave
        the equipment back at AVAILABLE and remove the active assignment from
        the list-active endpoint."""
        # 1. CHECKOUT
        checkout_id = self._checkout(client, eq_auth_headers, eq_item.id)
        list_resp = client.get('/api/v1/equipment/assignments', headers=eq_auth_headers)
        assert any(a['id'] == checkout_id for a in list_resp.json()['items']), (
            'Checkout must produce an active assignment'
        )

        # 2. CHECKIN
        checkin = client.post(
            f'/api/v1/equipment/assignments/{checkout_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert checkin.status_code == status.HTTP_200_OK

        # 3. Active list no longer includes the assignment
        list_resp_after = client.get(
            '/api/v1/equipment/assignments', headers=eq_auth_headers
        )
        assert not any(
            a['id'] == checkout_id for a in list_resp_after.json()['items']
        ), 'Check-in must remove the assignment from the active list'

        # 4. Item is back to AVAILABLE
        db_session.refresh(eq_item)
        meta = eq_item.meta_data or {}
        equipment_meta = meta.get('equipment', {}) if isinstance(meta, dict) else {}
        assert equipment_meta.get('equipment_status') == 'AVAILABLE'


@pytest.mark.integration
class TestAssignmentList:
    """Tests for listing active assignments."""

    def test_list_active_assignments(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Active assignment appears in list after checkout."""
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Bartosz'},
        )

        response = client.get('/api/v1/equipment/assignments', headers=eq_auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'items' in data
        assert 'total' in data
        assert any(a['item_id'] == str(eq_item.id) for a in data['items'])

    def test_item_assignment_history(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """History endpoint returns both active and completed assignments."""
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Charlie'},
        )

        response = client.get(
            f'/api/v1/equipment/assignments/item/{eq_item.id}',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) >= 1
        assert data[0]['item_id'] == str(eq_item.id)

    def test_item_assignment_history_names_the_operators(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """The history carries the account behind each handover, so a
        timeline can tell a holder's own return from one checked off for
        them by someone else."""
        created = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Charlie'},
        ).json()
        client.post(
            f'/api/v1/equipment/assignments/{created["id"]}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )

        response = client.get(
            f'/api/v1/equipment/assignments/item/{eq_item.id}',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        entry = response.json()['items'][0]
        # This run issued and checked in the return from the same account
        # (the fixture user, full_name derived from its email) — both names
        # are the account's, never the holder's free-text name.
        assert entry['checked_out_by_name'] == 'Equipment'
        assert entry['checked_in_by_name'] == 'Equipment'


@pytest.mark.integration
class TestMaintenanceLogs:
    """Tests for maintenance log endpoints."""

    def _create_log(
        self, client: TestClient, headers: dict[str, str], item_id: Any
    ) -> Any:  # httpx.Response; any return to allow callers chaining
        return client.post(
            '/api/v1/equipment/maintenance',
            headers=headers,
            json={
                'item_id': str(item_id),
                'maintenance_type': 'REPAIR',
                'title': 'Battery replacement',
                'performed_at': str(date.today()),
            },
        )

    def test_create_maintenance_log_success(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Creating a maintenance log entry returns 201."""
        response = self._create_log(client, eq_auth_headers, eq_item.id)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['title'] == 'Battery replacement'
        assert data['maintenance_type'] == 'REPAIR'
        assert data['item_id'] == str(eq_item.id)

    def test_get_item_maintenance_history(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Item maintenance history includes created log."""
        self._create_log(client, eq_auth_headers, eq_item.id)

        response = client.get(
            f'/api/v1/equipment/maintenance/item/{eq_item.id}',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) >= 1
        assert data[0]['item_id'] == str(eq_item.id)

    def test_update_maintenance_log(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """PUT on maintenance log updates fields."""
        log_id = self._create_log(client, eq_auth_headers, eq_item.id).json()['id']

        response = client.put(
            f'/api/v1/equipment/maintenance/{log_id}',
            headers=eq_auth_headers,
            json={'title': 'Screen replacement', 'cost': 250.00, 'currency': 'PLN'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['title'] == 'Screen replacement'
        assert float(data['cost']) == 250.0
        assert data['currency'] == 'PLN'

    def test_delete_maintenance_log(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """DELETE removes the maintenance log."""
        log_id = self._create_log(client, eq_auth_headers, eq_item.id).json()['id']

        response = client.delete(
            f'/api/v1/equipment/maintenance/{log_id}', headers=eq_auth_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Confirm deletion
        history = client.get(
            f'/api/v1/equipment/maintenance/item/{eq_item.id}',
            headers=eq_auth_headers,
        ).json()['items']
        assert not any(log['id'] == log_id for log in history)

    def test_invalid_maintenance_type_returns_422(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Unknown maintenance_type is rejected by schema validation."""
        response = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'INVALID_TYPE',
                'title': 'Test',
                'performed_at': str(date.today()),
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestEquipmentDashboard:
    """Tests for dashboard and warranty-alerts endpoints."""

    def test_dashboard_returns_totals(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Dashboard endpoint returns total_assets and by_status counts."""
        response = client.get('/api/v1/equipment/dashboard', headers=eq_auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'total_assets' in data
        assert 'by_status' in data
        assert 'active_assignments' in data
        assert data['total_assets'] >= 1

    def test_warranty_alerts_empty_by_default(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Without items with near-expiry warranties, alerts list is empty."""
        response = client.get(
            '/api/v1/equipment/warranty-alerts', headers=eq_auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json()['items'], list)

    def test_warranty_alerts_finds_expiring_asset(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Asset with warranty expiring within 30 days appears in alerts."""
        from sqlalchemy.orm.attributes import flag_modified

        soon = date.today() + timedelta(days=10)
        meta = dict(eq_item.meta_data or {})
        meta['equipment'] = {
            **meta.get('equipment', {}),
            'warranty_until': soon.isoformat(),
        }
        eq_item.meta_data = meta
        flag_modified(eq_item, 'meta_data')
        db_session.commit()

        response = client.get(
            '/api/v1/equipment/warranty-alerts?days=30', headers=eq_auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert any(a['item_id'] == str(eq_item.id) for a in data)
        alert = next(a for a in data if a['item_id'] == str(eq_item.id))
        assert alert['days_remaining'] <= 30

    def test_dashboard_lists_expired_warranty_separately(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """An asset whose warranty ended a year ago
        appears in the "expired" section and not in the expiring alerts."""
        from sqlalchemy.orm.attributes import flag_modified

        past = date.today() - timedelta(days=365)
        meta = dict(eq_item.meta_data or {})
        meta['equipment'] = {
            **meta.get('equipment', {}),
            'warranty_until': past.isoformat(),
        }
        eq_item.meta_data = meta
        flag_modified(eq_item, 'meta_data')
        db_session.commit()

        response = client.get('/api/v1/equipment/dashboard', headers=eq_auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        expired_ids = [a['item_id'] for a in data['expired_warranty_alerts']]
        expiring_ids = [a['item_id'] for a in data['warranty_alerts']]
        assert str(eq_item.id) in expired_ids
        assert str(eq_item.id) not in expiring_ids
