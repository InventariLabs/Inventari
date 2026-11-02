"""
Integration tests for bulk create and protocol PDF endpoints.

Covers:
- POST /equipment/items/bulk — bulk create
- GET /equipment/assignments/{id}/protocol/pdf
"""

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation


@pytest.mark.integration
class TestBulkCreate:
    def test_bulk_create_success(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json={
                'name': 'MacBook Air',
                'category_id': str(eq_category.id),
                'location_id': str(eq_storage_location.id),
                'brand': 'Apple',
                'entries': [
                    {'serial_number': 'SN-BULK-001'},
                    {'serial_number': 'SN-BULK-002'},
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['created'] == 2
        assert data['failed'] == 0
        assert len(data['items']) == 2

    def test_bulk_create_with_metadata(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json={
                'name': 'Test Item',
                'location_id': str(eq_storage_location.id),
                'metadata': {'equipment': {'manufacturer': 'Dell', 'model': 'XPS 15'}},
                'entries': [{'serial_number': 'SN-META-001'}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['created'] == 1

    def test_bulk_create_requires_auth(
        self, client: TestClient, eq_storage_location: StorageLocation
    ) -> None:
        response = client.post(
            '/api/v1/equipment/items/bulk',
            json={
                'name': 'Test',
                'location_id': str(eq_storage_location.id),
                'entries': [{'serial_number': 'SN-001'}],
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestProtocolPdf:
    def _checkout(
        self, client: TestClient, headers: dict[str, str], item_id: Any
    ) -> str:
        r = client.post(
            '/api/v1/equipment/assignments',
            headers=headers,
            json={'item_id': str(item_id), 'assigned_to_name': 'Alice'},
        )
        r.raise_for_status()
        return cast(str, r.json()['id'])

    def test_get_protocol_pdf_success(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        assignment_id = self._checkout(client, eq_auth_headers, eq_item.id)

        response = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/pdf',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get('content-type') == 'application/pdf'
        assert len(response.content) > 100

    def test_get_protocol_pdf_nonexistent_assignment(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            f'/api/v1/equipment/assignments/{uuid4()}/protocol/pdf',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
