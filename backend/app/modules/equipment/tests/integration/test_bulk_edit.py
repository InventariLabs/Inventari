"""
Integration tests for the Equipment bulk-edit (status change) endpoint.

Covers PATCH /api/v1/equipment/assets/bulk with action=change_status — the only
explicit status-change route. This is how a user records the start or end of
maintenance independently of the service log.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from starlette.testclient import TestClient

from app.models.item import Item


def _set_equipment_status(item: Item, db_session: Session, status_value: str) -> None:
    """Force an item's equipment_status in meta_data, persisting via flag_modified."""
    meta = dict(item.meta_data or {})
    meta['equipment'] = {**meta.get('equipment', {}), 'equipment_status': status_value}
    item.meta_data = meta
    flag_modified(item, 'meta_data')
    db_session.commit()


@pytest.mark.integration
class TestBulkEditStatus:
    """Tests for PATCH /equipment/assets/bulk with action=change_status."""

    def test_change_status_available_to_maintenance(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """AVAILABLE -> MAINTENANCE is a valid transition and updates meta_data."""
        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 1
        assert data['errors'] == []

        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'MAINTENANCE'

    def test_change_status_maintenance_to_available(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """MAINTENANCE -> AVAILABLE: the primary fix for the stuck-maintenance bug."""
        _set_equipment_status(eq_item, db_session, 'MAINTENANCE')

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'AVAILABLE'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 1
        assert data['errors'] == []

        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'AVAILABLE'

    def test_change_status_invalid_transition_reported_as_error(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """RETIRED -> DEPLOYED is forbidden by the state machine: surfaced per-item."""
        _set_equipment_status(eq_item, db_session, 'RETIRED')

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'DEPLOYED'},
            },
        )

        # 200 even when all items fail — the result carries the per-item error.
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 0
        assert len(data['errors']) == 1
        assert data['errors'][0]['item_id'] == str(eq_item.id)

    def test_change_status_invalid_status_value_reported_as_error(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """An unknown status value is caught by validate_transition (not a 422)."""
        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'BROKEN'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 0

    def test_a_refused_transition_reads_in_the_session_language_with_its_code(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """The bulk row speaks Polish to a Polish session and names its cause by code.

        The status machine answered in English for every reader here, because
        the bulk edit never passed it a language, and the row carried no code.
        """
        _set_equipment_status(eq_item, db_session, 'RETIRED')

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers={**eq_auth_headers, 'Accept-Language': 'pl'},
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'DEPLOYED'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        [error] = response.json()['errors']
        assert error['item_id'] == str(eq_item.id)
        assert error['code'] == 'EQUIPMENT_STATUS_TRANSITION_FROM_RETIRED'
        assert error['error'] == (
            'Nie można zmienić statusu z RETIRED na DEPLOYED. '
            'Wycofane zasoby muszą być najpierw jawnie przywrócone.'
        )

    # --- Retiring an asset must close its active assignment --------------

    def _checkout(
        self, client: TestClient, headers: dict[str, str], item_id: Any
    ) -> None:
        r = client.post(
            '/api/v1/equipment/assignments',
            headers=headers,
            json={'item_id': str(item_id), 'assigned_to_name': 'E9-Tester'},
        )
        r.raise_for_status()

    def test_change_status_to_retired_closes_active_assignment(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Changing status to RETIRED while an asset has an active
        assignment must auto-close that assignment (no double-booking)."""
        from app.modules.equipment.models import EquipmentAssignment

        self._checkout(client, eq_auth_headers, eq_item.id)

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'RETIRED'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 1
        assert data['errors'] == []

        # Active assignment must no longer exist for this item.
        active = (
            db_session.query(EquipmentAssignment)
            .filter(
                EquipmentAssignment.item_id == eq_item.id,
                EquipmentAssignment.organization_id == eq_item.organization_id,
                EquipmentAssignment.checked_in_at.is_(None),
            )
            .first()
        )
        assert active is None, 'RETIRED must auto-close the active assignment'

        # Status should land at RETIRED (not silently reset to AVAILABLE).
        db_session.refresh(eq_item)
        meta = eq_item.meta_data or {}
        equipment_meta = meta.get('equipment', {}) if isinstance(meta, dict) else {}
        assert equipment_meta.get('equipment_status') == 'RETIRED'

    def test_change_status_to_retired_no_active_assignment_succeeds(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Retiring an asset with no active assignment must still work."""
        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'RETIRED'},
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 1
        assert data['errors'] == []

        db_session.refresh(eq_item)
        meta = eq_item.meta_data or {}
        equipment_meta = meta.get('equipment', {}) if isinstance(meta, dict) else {}
        assert equipment_meta.get('equipment_status') == 'RETIRED'

    def test_change_status_to_maintenance_keeps_assignment_open(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Sending the asset to MAINTENANCE must NOT close the active assignment
        (the asset will be repaired and returned to the assignee)."""
        from app.modules.equipment.models import EquipmentAssignment

        self._checkout(client, eq_auth_headers, eq_item.id)

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 1
        assert data['errors'] == []

        active = (
            db_session.query(EquipmentAssignment)
            .filter(
                EquipmentAssignment.item_id == eq_item.id,
                EquipmentAssignment.organization_id == eq_item.organization_id,
                EquipmentAssignment.checked_in_at.is_(None),
            )
            .first()
        )
        assert active is not None, 'MAINTENANCE must NOT close the active assignment'

    # --- Status / assignment consistency guards (drift fix) -----------------

    def test_change_status_to_available_with_active_assignment_returns_error(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """An asset with an active checkout must NOT be silently set to AVAILABLE
        — that would hide an open assignment and desync the two sources of truth
        (the dashboard "Checked Out" tile counts assignments, the list filters by
        status). The user must check it in first."""
        self._checkout(client, eq_auth_headers, eq_item.id)
        # Checkout flips the status to DEPLOYED.
        db_session.refresh(eq_item)
        assert (eq_item.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'DEPLOYED'

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'AVAILABLE'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 0
        assert len(data['errors']) == 1
        assert data['errors'][0]['item_id'] == str(eq_item.id)
        assert data['errors'][0]['code'] == 'EQUIPMENT_STILL_ASSIGNED'

        # Status must remain unchanged (DEPLOYED), not reset to AVAILABLE.
        db_session.refresh(eq_item)
        assert (eq_item.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'DEPLOYED'

    def test_change_status_to_deployed_without_assignment_returns_error(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Setting status to DEPLOYED without an active assignment would create
        the mirror-image drift (status says deployed, but nobody holds it). The
        user must use checkout to deploy an asset."""
        # eq_item starts AVAILABLE with no assignment.

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'DEPLOYED'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 0
        assert len(data['errors']) == 1
        assert data['errors'][0]['item_id'] == str(eq_item.id)
        assert data['errors'][0]['code'] == 'EQUIPMENT_DEPLOY_REQUIRES_CHECKOUT'

        # Status must remain AVAILABLE, not set to DEPLOYED.
        db_session.refresh(eq_item)
        assert (eq_item.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'AVAILABLE'

    def test_change_status_to_maintenance_with_active_assignment_succeeds(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """MAINTENANCE is still allowed while an asset is checked out — the asset
        is being repaired and will return to the same assignee (the assignment
        is intentionally left open)."""
        self._checkout(client, eq_auth_headers, eq_item.id)

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 1
        assert data['errors'] == []

        db_session.refresh(eq_item)
        assert (eq_item.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'MAINTENANCE'

    def test_unknown_action_returns_422(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """The action field is regex-validated: an unknown value is a 422."""
        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'delete_everything',
                'data': {},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_change_status_missing_status_reported_as_error(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """change_status without a status value is a per-item error, not a crash."""
        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['updated'] == 0
        assert len(data['errors']) == 1
