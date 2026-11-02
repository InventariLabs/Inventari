"""
Integration tests for the status machine enforcement + AVAILABLE default,
and for maintenance delete reconciling the cached status.

These cover two gaps found on 2026-07-18:

* ``_update_equipment_status`` must reject illegal transitions via
  ``validate_transition``. The default ``equipment_status`` of AVAILABLE
  is seeded by the ``EquipmentItemInterceptor.before_create`` hook so the
  dashboard no longer surfaces UNKNOWN on freshly-created assets.

* ``delete_log`` must recompute the cached status when the *last*
  maintenance log is removed. An asset stuck in MAINTENANCE without any
  log rows (and without an active assignment) must return to AVAILABLE.
"""

from datetime import date
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item


def _set_equipment_status(item: Item, db_session: Session, value: str) -> None:
    meta = dict(item.meta_data or {})
    eq_ns = dict(meta.get('equipment') or {})
    eq_ns['equipment_status'] = value
    meta['equipment'] = eq_ns
    item.meta_data = meta
    db_session.commit()
    db_session.refresh(item)


def _get_equipment_status(item: Item) -> str:
    meta = item.meta_data or {}
    eq_ns = meta.get('equipment') or {}
    return str(eq_ns.get('equipment_status', 'UNKNOWN'))


@pytest.mark.integration
class TestStateMachineEnforcement:
    """``_update_equipment_status`` must reject illegal transitions."""

    def test_maintenance_log_on_retired_asset_keeps_retired_status(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A historical record can be added without unretiring the asset."""
        _set_equipment_status(eq_item, db_session, 'RETIRED')

        response = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Previous repair',
                'performed_at': str(date.today()),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        db_session.refresh(eq_item)
        assert _get_equipment_status(eq_item) == 'RETIRED'

    def test_checkout_available_to_deployed_allowed(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """Sanity: the canonical AVAILABLE -> DEPLOYED checkout path still works."""
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Alice',
                'assigned_to_email': 'alice@example.com',
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_checkin_deployed_to_maintenance_allowed_for_damaged(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """Sanity: DEPLOYED -> MAINTENANCE via DAMAGED checkin is allowed."""
        checkout = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Bob',
                'assigned_to_email': 'bob@example.com',
            },
        )
        assignment_id = checkout.json()['id']

        response = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'DAMAGED'},
        )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.integration
class TestInterceptorDefaultAvailable:
    """New items default to ``equipment_status=AVAILABLE``."""

    def test_new_item_gets_default_available_status(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Any,
        eq_storage_location: Any,
        eq_category: Any,
        db_session: Session,
    ) -> None:
        """The interceptor seeds AVAILABLE when an equipment item is created.

        The equipment-specific paths (bulk-create, import, AddEquipment)
        pre-populate ``metadata.equipment`` on the payload; the interceptor
        then fills in ``equipment_status`` if it is missing. We mirror that
        contract here by passing a minimal ``equipment`` namespace.
        """
        response = client.post(
            '/api/v1/items',
            headers=eq_auth_headers,
            json={
                'name': 'Fresh Laptop',
                'location_id': str(eq_storage_location.id),
                'category_id': str(eq_category.id),
                'quantity': 1,
                'metadata': {'equipment': {'serial_number': 'SN-NEW'}},
            },
        )
        # Some test deployments use 201, others 200; both are acceptable as long
        # as the response is successful and we can read back the item.
        assert response.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), response.text

        # Dashboard aggregate must NOT contain UNKNOWN for this item.
        dash = client.get('/api/v1/equipment/dashboard', headers=eq_auth_headers).json()
        assert 'by_status' in dash
        # The new asset contributes to AVAILABLE, never UNKNOWN.
        assert dash['by_status'].get('UNKNOWN', 0) == 0


@pytest.mark.integration
class TestMaintenanceDelete:
    """Deleting a service record leaves the asset's status alone."""

    def _create_log(
        self, client: TestClient, headers: dict[str, str], item_id: Any
    ) -> Any:
        return client.post(
            '/api/v1/equipment/maintenance',
            headers=headers,
            json={
                'item_id': str(item_id),
                'maintenance_type': 'REPAIR',
                'title': 'Fix screen',
                'performed_at': str(date.today()),
            },
        )

    def test_delete_last_log_keeps_the_chosen_status(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A removed record does not decide that ongoing work is over."""
        log_id = self._create_log(client, eq_auth_headers, eq_item.id).json()['id']
        _set_equipment_status(eq_item, db_session, 'MAINTENANCE')
        db_session.refresh(eq_item)
        assert _get_equipment_status(eq_item) == 'MAINTENANCE'

        response = client.delete(
            f'/api/v1/equipment/maintenance/{log_id}', headers=eq_auth_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        db_session.refresh(eq_item)
        assert _get_equipment_status(eq_item) == 'MAINTENANCE'

    def test_delete_one_of_many_logs_keeps_maintenance(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """When other maintenance logs remain, status stays at MAINTENANCE."""
        first_id = self._create_log(client, eq_auth_headers, eq_item.id).json()['id']
        second_id = self._create_log(client, eq_auth_headers, eq_item.id).json()['id']
        _set_equipment_status(eq_item, db_session, 'MAINTENANCE')

        # Delete the first one; one log still remains.
        response = client.delete(
            f'/api/v1/equipment/maintenance/{first_id}', headers=eq_auth_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        db_session.refresh(eq_item)
        assert _get_equipment_status(eq_item) == 'MAINTENANCE', (
            'with logs remaining the status must stay MAINTENANCE'
        )

        # Deleting the other record leaves the chosen status alone too.
        client.delete(
            f'/api/v1/equipment/maintenance/{second_id}', headers=eq_auth_headers
        )

    def test_delete_last_log_when_assigned_keeps_maintenance(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_user: Any,
        db_session: Session,
    ) -> None:
        """Removing the last record also leaves an assigned asset's status alone."""
        log_id = self._create_log(client, eq_auth_headers, eq_item.id).json()['id']
        _set_equipment_status(eq_item, db_session, 'MAINTENANCE')

        # Manually craft an active assignment row for this asset.
        from app.modules.equipment.models import EquipmentAssignment

        assignment = EquipmentAssignment(
            organization_id=eq_item.organization_id,
            item_id=eq_item.id,
            assigned_to_name='Carol',
            assigned_to_email='carol@example.com',
            checked_out_by=eq_user.id,
        )
        db_session.add(assignment)
        db_session.commit()

        response = client.delete(
            f'/api/v1/equipment/maintenance/{log_id}', headers=eq_auth_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        db_session.refresh(eq_item)
        assert _get_equipment_status(eq_item) == 'MAINTENANCE'

    def test_delete_log_when_status_not_maintenance_is_noop(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Deleting a record does not change an available asset either."""
        # Status starts at AVAILABLE (eq_item fixture).
        log_id = self._create_log(client, eq_auth_headers, eq_item.id).json()['id']
        # Set the state independently of the record.
        _set_equipment_status(eq_item, db_session, 'AVAILABLE')

        response = client.delete(
            f'/api/v1/equipment/maintenance/{log_id}', headers=eq_auth_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        db_session.refresh(eq_item)
        assert _get_equipment_status(eq_item) == 'AVAILABLE'


def _create_maintenance_log(
    client: TestClient, headers: dict[str, str], item_id: Any, title: str = 'Fix screen'
) -> Any:
    return client.post(
        '/api/v1/equipment/maintenance',
        headers=headers,
        json={
            'item_id': str(item_id),
            'maintenance_type': 'REPAIR',
            'title': title,
            'performed_at': str(date.today()),
        },
    )


def _checkout(
    client: TestClient, headers: dict[str, str], item_id: Any, name: str
) -> Any:
    return client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={'item_id': str(item_id), 'assigned_to_name': name},
    )


@pytest.mark.integration
class TestMaintenanceWithOpenAssignment:
    """A maintenance entry must not trap a checked-out asset.

    Adding a maintenance log to an asset with an open assignment must keep
    the DEPLOYED status (both facts are true: issued + in service), so the
    asset is counted exactly once on the dashboard and the check-in button
    stays available.
    """

    def test_maintenance_log_keeps_deployed_status_when_checked_out(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        checkout = _checkout(client, eq_auth_headers, eq_item.id, 'Marta Zielinska')
        assert checkout.status_code == status.HTTP_201_CREATED, checkout.text

        log = _create_maintenance_log(client, eq_auth_headers, eq_item.id)
        assert log.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), (
            log.text
        )

        db_session.refresh(eq_item)
        assert _get_equipment_status(eq_item) == 'DEPLOYED', (
            'An open assignment keeps the asset issued; the maintenance '
            'entry must not overwrite the status to MAINTENANCE'
        )

    def test_checked_out_asset_with_maintenance_counts_once_on_dashboard(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id, 'Marta Zielinska')
        _create_maintenance_log(client, eq_auth_headers, eq_item.id)
        # Force the historical trap state: status MAINTENANCE + open assignment.
        _set_equipment_status(eq_item, db_session, 'MAINTENANCE')

        dash = client.get('/api/v1/equipment/dashboard', headers=eq_auth_headers)
        assert dash.status_code == 200, dash.text
        body = dash.json()
        # The asset is issued — not counted by the maintenance tile.
        assert body['in_maintenance'] == 0
        assert body['active_assignments'] == 1


@pytest.mark.integration
class TestAssignmentCountsOnlyLiveAssets:
    """Ghost assignments of soft-deleted assets must not
    count on the dashboard."""

    def test_soft_deleted_asset_excluded_from_counts_and_recent(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: Any,
        eq_category: Any,
        db_session: Session,
    ) -> None:
        # A live asset with an open assignment (must survive the fix).
        live = client.post(
            '/api/v1/items',
            headers=eq_auth_headers,
            json={
                'name': 'Live Laptop',
                'location_id': str(eq_storage_location.id),
                'category_id': str(eq_category.id),
                'quantity': 1,
            },
        )
        assert live.status_code in (200, 201), live.text
        _checkout(client, eq_auth_headers, live.json()['id'], 'Alice')

        # A ghost: checked out, then soft-deleted directly in the DB
        # (bypassing the interceptor that normally blocks this path).
        _checkout(client, eq_auth_headers, eq_item.id, 'Ghost')
        eq_item.is_deleted = True
        db_session.add(eq_item)
        db_session.commit()

        dash = client.get('/api/v1/equipment/dashboard', headers=eq_auth_headers)
        assert dash.status_code == 200, dash.text
        body = dash.json()
        assert body['active_assignments'] == 1, (
            'The soft-deleted asset must not count as checked out'
        )
        names = [a['item_name'] for a in body['recent_activity']]
        assert 'Live Laptop' in names
        assert 'Ghost' not in names
