"""
Integration tests for Cycle Count Schedules.

Tests verify:
- CRUD for cycle count schedules
- Manual trigger generates StockTake with filtered items
- Sample size limits item count
- Schedule without storage_location_id rejected
"""

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation


@pytest.fixture
def schedule_payload(test_storage_location: StorageLocation) -> dict[str, Any]:
    return {
        'name': 'Weekly A-items',
        'frequency': 'weekly',
        'scope': 'all',
        'location_id': str(test_storage_location.id),
    }


@pytest.mark.integration
class TestCycleCountScheduleCRUD:
    def test_create_schedule(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        schedule_payload: dict[str, Any],
    ) -> None:
        resp = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json=schedule_payload,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['name'] == 'Weekly A-items'
        assert data['frequency'] == 'weekly'
        assert data['scope'] == 'all'
        assert data['is_active'] is True

    def test_list_schedules(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        schedule_payload: dict[str, Any],
    ) -> None:
        client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json=schedule_payload,
        )
        resp = client.get(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) >= 1

    def test_get_schedule(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        schedule_payload: dict[str, Any],
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json=schedule_payload,
        )
        schedule_id = create.json()['id']

        resp = client.get(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['id'] == schedule_id

    def test_update_schedule(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        schedule_payload: dict[str, Any],
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json=schedule_payload,
        )
        schedule_id = create.json()['id']

        resp = client.patch(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}',
            headers=auth_headers,
            json={'name': 'Monthly B-items', 'frequency': 'monthly'},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['name'] == 'Monthly B-items'
        assert resp.json()['frequency'] == 'monthly'

    def test_a_named_null_clears_a_nullable_column_and_refuses_a_required_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        schedule_payload: dict[str, Any],
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json={**schedule_payload, 'tolerance_percent': 10},
        )
        schedule_id = create.json()['id']
        assert create.json()['tolerance_percent'] == '10.00'

        cleared = client.patch(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}',
            headers=auth_headers,
            json={'tolerance_percent': None},
        )
        assert cleared.status_code == status.HTTP_200_OK, cleared.text
        assert cleared.json()['tolerance_percent'] is None

        refused = client.patch(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}',
            headers=auth_headers,
            json={'name': None},
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'name' in refused.json()['detail']['message']

    def test_delete_schedule(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        schedule_payload: dict[str, Any],
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json=schedule_payload,
        )
        schedule_id = create.json()['id']

        resp = client.delete(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        get_resp = client.get(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}',
            headers=auth_headers,
        )
        assert get_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestCycleCountGenerate:
    def test_run_generates_stock_take(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json={
                'name': 'Full count',
                'frequency': 'monthly',
                'scope': 'all',
                'location_id': str(test_storage_location.id),
            },
        )
        schedule_id = create.json()['id']

        resp = client.post(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}/run',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['status'] == 'in_progress'
        assert data['items_count'] == 5
        assert data['blind_mode'] is True
        assert 'Cycle Count: Full count' in data['name']

    def test_run_with_sample_size(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json={
                'name': 'Sample count',
                'frequency': 'weekly',
                'scope': 'all',
                'sample_size': 2,
                'location_id': str(test_storage_location.id),
            },
        )
        schedule_id = create.json()['id']

        resp = client.post(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}/run',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['items_count'] == 2

    def test_run_without_storage_location_fails(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json={
                'name': 'No location',
                'frequency': 'monthly',
                'scope': 'all',
            },
        )
        schedule_id = create.json()['id']

        resp = client.post(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}/run',
            headers=auth_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_run_updates_last_run_at(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        create = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json={
                'name': 'Timestamp test',
                'frequency': 'monthly',
                'scope': 'all',
                'location_id': str(test_storage_location.id),
            },
        )
        schedule_id = create.json()['id']

        client.post(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}/run',
            headers=auth_headers,
        )

        resp = client.get(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule_id}',
            headers=auth_headers,
        )
        assert resp.json()['last_run_at'] is not None
