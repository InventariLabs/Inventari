"""
Integration tests for item_history logging in the equipment module.

Covers:
- STATUS_CHANGED logged on retire
- MAINTENANCE action logged on maintenance log creation
"""

from datetime import date

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.item_history import ItemHistory


@pytest.mark.integration
class TestItemHistoryRetire:
    def test_retire_logs_status_changed(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        response = client.post(
            f'/api/v1/equipment/items/{eq_item.id}/retire',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        history = list(
            db_session.scalars(
                select(ItemHistory).where(
                    ItemHistory.item_id == eq_item.id,
                    ItemHistory.action == 'STATUS_CHANGED',
                )
            ).all()
        )
        assert len(history) == 1
        changes = history[0].changes
        assert changes is not None
        assert changes['old_status'] == 'AVAILABLE'
        assert changes['new_status'] == 'RETIRED'

    def test_bulk_retire_logs_status_changed_per_item(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        from app.models.item import Item

        item2 = Item(
            organization_id=eq_item.organization_id,
            storage_location_id=eq_item.storage_location_id,
            category_id=eq_item.category_id,
            name='Dell Latitude',
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'DEPLOYED'}},
        )
        db_session.add(item2)
        db_session.commit()

        response = client.post(
            '/api/v1/equipment/items/bulk-retire',
            headers=eq_auth_headers,
            json=[str(eq_item.id), str(item2.id)],
        )
        assert response.status_code == status.HTTP_200_OK

        history = list(
            db_session.scalars(
                select(ItemHistory).where(
                    ItemHistory.item_id.in_([eq_item.id, item2.id]),
                    ItemHistory.action == 'STATUS_CHANGED',
                )
            ).all()
        )
        assert len(history) == 2
        status_changes = {h.item_id: h.changes for h in history}
        eq_changes = status_changes[eq_item.id]
        item2_changes = status_changes[item2.id]
        assert eq_changes is not None and eq_changes['new_status'] == 'RETIRED'
        assert item2_changes is not None and item2_changes['new_status'] == 'RETIRED'


@pytest.mark.integration
class TestItemHistoryMaintenance:
    def test_create_maintenance_log_logs_maintenance_action(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        response = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Screen replacement',
                'description': 'Cracked display panel',
                'cost': 450.00,
                'currency': 'PLN',
                'performed_at': '2026-05-17',
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        history = list(
            db_session.scalars(
                select(ItemHistory).where(
                    ItemHistory.item_id == eq_item.id,
                    ItemHistory.action == 'MAINTENANCE',
                )
            ).all()
        )
        assert len(history) == 1
        changes = history[0].changes
        assert changes is not None
        assert changes['type'] == 'REPAIR'
        assert changes['title'] == 'Screen replacement'
        assert changes['cost'] == 450.0

    @pytest.mark.parametrize('day', ['2020-01-01', date.today().isoformat()])
    def test_recording_service_does_not_change_the_chosen_status(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
        day: str,
    ) -> None:
        response = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'CLEANING',
                'title': 'Cleaning',
                'performed_at': day,
            },
        )
        assert response.status_code == 201, response.text
        db_session.expire_all()
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'AVAILABLE'
        assert not db_session.scalars(
            select(ItemHistory).where(
                ItemHistory.item_id == eq_item.id,
                ItemHistory.action == 'STATUS_CHANGED',
            )
        ).all()

    def test_create_maintenance_log_no_status_change_when_already_maintenance(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        eq_item.meta_data = {
            'equipment': {'serial_number': 'SN-001', 'equipment_status': 'MAINTENANCE'}
        }
        db_session.commit()

        response = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Follow-up fix',
                'performed_at': '2026-05-17',
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        status_changed = list(
            db_session.scalars(
                select(ItemHistory).where(
                    ItemHistory.item_id == eq_item.id,
                    ItemHistory.action == 'STATUS_CHANGED',
                )
            ).all()
        )
        assert len(status_changed) == 0

        maintenance = list(
            db_session.scalars(
                select(ItemHistory).where(
                    ItemHistory.item_id == eq_item.id,
                    ItemHistory.action == 'MAINTENANCE',
                )
            ).all()
        )
        assert len(maintenance) == 1
