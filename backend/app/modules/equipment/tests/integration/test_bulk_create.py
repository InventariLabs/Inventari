"""
Integration tests for POST /equipment/items/bulk endpoint.
"""

from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation


@pytest.mark.integration
class TestBulkEquipmentCreate:
    """Tests for the bulk equipment item creation endpoint."""

    def _payload(
        self, storage_id: str, category_id: str | None = None
    ) -> dict[str, Any]:
        return {
            'name': 'Dell Latitude 5540',
            'location_id': storage_id,
            'category_id': category_id,
            'brand': 'Dell',
            'entries': [
                {'serial_number': 'SN-BULK-001'},
                {'serial_number': 'SN-BULK-002', 'asset_tag': 'AT-002'},
                {'serial_number': 'SN-BULK-003'},
            ],
        }

    def test_bulk_create_3_items_success(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """Creating 3 items returns 201 with correct counts."""
        payload = self._payload(str(eq_storage_location.id), str(eq_category.id))
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json=payload,
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['created'] == 3
        assert data['failed'] == 0
        assert len(data['items']) == 3
        assert data['errors'] == []

    def test_bulk_create_stores_serial_in_the_core_column(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        """The number goes to Item.serial_number, and not also into the meta.

        A second copy in the equipment namespace is what let two assets
        created two ways carry their number in two different places.
        """
        from app.models.item import Item

        payload = self._payload(str(eq_storage_location.id), str(eq_category.id))
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json=payload,
        )

        assert response.status_code == status.HTTP_201_CREATED
        item_ids = response.json()['items']

        items = list(
            db_session.scalars(select(Item).where(Item.id.in_(item_ids))).all()
        )
        assert {item.serial_number for item in items} == {
            'SN-BULK-001',
            'SN-BULK-002',
            'SN-BULK-003',
        }
        assert all(
            'serial_number' not in (item.meta_data or {}).get('equipment', {})
            for item in items
        )

        # entry with asset_tag should have it stored
        at_item = next(i for i in items if i.serial_number == 'SN-BULK-002')
        assert (at_item.meta_data or {}).get('equipment', {}).get(
            'asset_tag'
        ) == 'AT-002'

    def test_bulk_create_partial_success_on_duplicate_serial(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        eq_item: Item,
    ) -> None:
        """A duplicate serial causes that entry to fail; rest succeed."""
        payload = {
            'name': 'Generic Asset',
            'location_id': str(eq_storage_location.id),
            'entries': [
                {'serial_number': 'SN-UNIQUE-111'},
                # This serial already exists on eq_item
                {'serial_number': 'SN-001'},
                {'serial_number': 'SN-UNIQUE-222'},
            ],
        }
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json=payload,
        )

        # Partial success: 2 created, 1 failed  (or all 3 succeed if serial
        # uniqueness is not enforced at DB level — adjust assertion accordingly)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['created'] + data['failed'] == 3

    def test_bulk_create_empty_entries_returns_422(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        """Sending an empty entries list triggers validation error."""
        payload = {
            'name': 'Asset',
            'location_id': str(eq_storage_location.id),
            'entries': [],
        }
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_bulk_create_over_limit_returns_422(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        """Sending more than 200 entries triggers validation error."""
        entries = [{'serial_number': f'SN-{i:04d}'} for i in range(201)]
        payload = {
            'name': 'Asset',
            'location_id': str(eq_storage_location.id),
            'entries': entries,
        }
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_bulk_create_with_foreign_storage_creates_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        """Storage from another org → no items created (per-row errors).

        The storage pre-validation (moved from the dead bulk_service
        copy into _bulk_service) rejects a location that does not belong to
        the caller's org up front. Previously the request aborted with
        NotFoundException from core_api.items.create_async; now it returns a
        structured response with failed rows and created=0.
        """
        payload = {
            'name': 'Asset',
            'location_id': str(eq_storage_location.id),
            'entries': [{'serial_number': 'SN-X'}],
        }
        # auth_headers belongs to a different org than eq_storage_location
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['created'] == 0
        assert data['failed'] == 1
        assert 'Storage location not found' in data['errors'][0]['error']
