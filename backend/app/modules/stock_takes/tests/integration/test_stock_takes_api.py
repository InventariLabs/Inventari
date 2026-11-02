"""
Integration tests for stock takes API endpoints.

Tests verify correctness of endpoints:
- POST /api/stock-takes - create stock take
- GET /api/stock-takes - list stock takes
- GET /api/stock-takes/{stock_take_id} - stock take details
- PUT /api/stock-takes/{stock_take_id} - update stock take
- PATCH /api/stock-takes/{stock_take_id}/status - change status
- DELETE /api/stock-takes/{stock_take_id} - delete stock take
- GET /api/stock-takes/{stock_take_id}/items - stock take items
- PATCH /api/stock-takes/{stock_take_id}/items/{item_id}/count - count item
- PATCH /api/stock-takes/{stock_take_id}/items/bulk-count - bulk count
- POST /api/stock-takes/{stock_take_id}/complete - finalize stock take
- GET /api/stock-takes/{stock_take_id}/report - stock take report
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTakeStatus


@pytest.mark.integration
class TestStockTakesCreate:
    """Tests for stock take creation endpoint."""

    def test_create_stock_take_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Tests successful stock take creation."""
        response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Test Stock Take',
                'description': 'Test stock take',
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Test Stock Take'
        assert data['status'] == StockTakeStatus.IN_PROGRESS.value
        assert 'id' in data

    def test_create_stock_take_with_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        """Tests creating stock take with automatic items."""
        response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Stock take with products',
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['items_count'] == 5  # 5 items in batch

    def test_create_stock_take_invalid_storage(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests creating stock take with invalid storage."""
        from uuid import uuid4

        response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={'name': 'Stock Take', 'location_id': str(uuid4())},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_stock_take_duplicate_active(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests creating second active stock take."""
        response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Second stock take',
                'location_id': str(test_stock_take.storage_location_id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            'active stock take already exists' in response.json()['detail']['message']
        )

    def test_create_stock_take_persists_counting_options(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Options from the creation dialog must be persisted on the stock take.

        Regression guard for: the router used to pass only name,
               description and notes to the service, silently dropping
               blind_mode, tolerance_percent and require_full_count.
        """
        response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Options stock take',
                'location_id': str(test_storage_location.id),
                'blind_mode': True,
                'tolerance_percent': 2.0,
                'require_full_count': False,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['blind_mode'] is True
        assert Decimal(data['tolerance_percent']) == 2
        assert data['require_full_count'] is False


@pytest.mark.integration
class TestStockTakesList:
    """Tests for stock takes list endpoint."""

    def test_get_stock_takes_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests fetching empty stock takes list."""
        response = client.get('/api/v1/stock-takes', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []
        assert data['total'] == 0

    def test_get_stock_takes_with_data(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests fetching stock takes list with data."""
        response = client.get('/api/v1/stock-takes', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 1
        assert data['total'] == 1

    def test_get_stock_takes_names_who_started_each_one(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """The list is how somebody returns to their own count.

        The card carried the date and the place and never the person, though
        the row has held `user_id` all along.
        """
        response = client.get('/api/v1/stock-takes', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        row = response.json()['items'][0]
        assert row['started_by_name']

    def test_get_stock_takes_filter_by_storage(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests filtering stock takes by storage location."""
        response = client.get(
            f'/api/v1/stock-takes?location_id={test_stock_take.storage_location_id}',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) >= 1

    def test_get_stock_takes_filter_by_status(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests filtering stock takes by status."""
        response = client.get(
            f'/api/v1/stock-takes?status_filter={StockTakeStatus.IN_PROGRESS.value}',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) >= 1

    def test_get_stock_takes_pagination(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests stock takes list pagination."""
        response = client.get(
            '/api/v1/stock-takes?offset=0&limit=10', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) <= 10
        assert data['total'] >= 1

    def test_list_includes_progress_and_location(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        test_storage_location: StorageLocation,
    ) -> None:
        """list rows must carry progress and the storage location name.

        Previously the row was built only from table columns, so the UI
        showed 0 % progress at 12/12 and "unknown place" even though the
        relation was loaded and left unused.
        """
        items = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items', headers=auth_headers
        ).json()['items']
        assert len(items) == 5

        count_response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/{items[0]["id"]}/count',
            headers=auth_headers,
            json={'counted_quantity': 1},
        )
        assert count_response.status_code == status.HTTP_200_OK

        response = client.get('/api/v1/stock-takes', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        row = next(
            r for r in response.json()['items'] if r['id'] == str(test_stock_take.id)
        )
        assert row['location_name'] == test_storage_location.name
        assert row['progress_percent'] == 20.0


@pytest.mark.integration
class TestStockTakeDetails:
    """Tests for stock take details endpoint."""

    def test_get_stock_take_success(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests successful stock take details fetching."""
        response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_stock_take.id)
        assert data['name'] == test_stock_take.name
        assert 'items' in data

    def test_get_stock_take_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests fetching non-existent stock take."""
        from uuid import uuid4

        response = client.get(f'/api/v1/stock-takes/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestStockTakeUpdate:
    """Tests for stock take update endpoint."""

    def test_update_stock_take_success(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests successful stock take update."""
        response = client.put(
            f'/api/v1/stock-takes/{test_stock_take.id}',
            headers=auth_headers,
            json={'name': 'Updated stock take', 'description': 'Updated description'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Updated stock take'

    def test_update_stock_take_completed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        """Tests updating completed stock take."""
        # Create completed stock take
        from app.modules.stock_takes.models import StockTake

        stock_take = StockTake(
            user_id=test_items_batch[0].storage_location.created_by,
            organization_id=test_items_batch[0].storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='Completed stock take',
            status=StockTakeStatus.COMPLETED,
        )
        db_session.add(stock_take)
        db_session.commit()

        response = client.put(
            f'/api/v1/stock-takes/{stock_take.id}',
            headers=auth_headers,
            json={'name': 'New name'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestStockTakeStatusUpdate:
    """Tests for stock take status update endpoint."""

    def test_update_status_to_completed_is_refused(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Closing goes through finalisation, which posts the adjustments."""
        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/status',
            headers=auth_headers,
            json={'status': StockTakeStatus.COMPLETED.value},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_status_to_cancelled(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests changing status to cancelled."""
        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/status',
            headers=auth_headers,
            json={'status': StockTakeStatus.CANCELLED.value},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == StockTakeStatus.CANCELLED.value

    def test_update_status_invalid_transition(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        """Tests invalid status change attempt."""
        # Create completed stock take
        from app.modules.stock_takes.models import StockTake

        stock_take = StockTake(
            user_id=test_items_batch[0].storage_location.created_by,
            organization_id=test_items_batch[0].storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='Completed',
            status=StockTakeStatus.COMPLETED,
        )
        db_session.add(stock_take)
        db_session.commit()

        response = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/status',
            headers=auth_headers,
            json={'status': StockTakeStatus.IN_PROGRESS.value},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestStockTakeDelete:
    """Tests for stock take deletion endpoint."""

    def test_delete_stock_take_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        """Tests successful stock take deletion."""
        # Create stock take to delete
        from app.modules.stock_takes.models import StockTake

        stock_take = StockTake(
            user_id=test_items_batch[0].storage_location.created_by,
            organization_id=test_items_batch[0].storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='To delete',
            status=StockTakeStatus.DRAFT,
        )
        db_session.add(stock_take)
        db_session.commit()

        response = client.delete(
            f'/api/v1/stock-takes/{stock_take.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_stock_take_completed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        """Tests deleting completed stock take."""
        # Create completed stock take
        from app.modules.stock_takes.models import StockTake

        stock_take = StockTake(
            user_id=test_items_batch[0].storage_location.created_by,
            organization_id=test_items_batch[0].storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='Completed',
            status=StockTakeStatus.COMPLETED,
        )
        db_session.add(stock_take)
        db_session.commit()

        response = client.delete(
            f'/api/v1/stock-takes/{stock_take.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestStockTakeItems:
    """Tests for stock take items endpoint."""

    def test_get_stock_take_items(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests fetching stock take items."""
        response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        assert len(items) == 5  # 5 items in batch

    def test_get_stock_take_items_filter_counted(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests filtering items by counted status."""
        response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items?include_counted=true',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        # All items should be counted (or not)
        for item in items:
            assert item['counted_quantity'] is not None

    def test_get_stock_take_items_search(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests searching items."""
        response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items?search=Product',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        # Check that all items contain "Product"
        for item in items:
            assert 'Product' in item['item_name']


@pytest.mark.integration
class TestStockTakeItemCount:
    """Tests for stock take item count endpoint."""

    def test_count_stock_take_item(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests counting single item."""
        # Get items
        items_response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items', headers=auth_headers
        )
        items = items_response.json()['items']
        item_id = items[0]['id']

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/{item_id}/count',
            headers=auth_headers,
            json={
                'counted_quantity': 10,
                'shelf_location': 'Shelf 1',
                'notes': 'Found 10 units',
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['counted_quantity']) == 10
        assert data['shelf_location'] == 'Shelf 1'

    def test_count_stock_take_item_with_discrepancy(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests counting item with discrepancy."""
        # Get items
        items_response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items', headers=auth_headers
        )
        items = items_response.json()['items']
        item_id = items[0]['id']
        system_quantity = Decimal(items[0]['system_quantity'])

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/{item_id}/count',
            headers=auth_headers,
            json={'counted_quantity': str(system_quantity + 5)},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_discrepancy'] == 1


@pytest.mark.integration
class TestStockTakeComplete:
    """Tests for stock take completion endpoint."""

    def test_complete_stock_take_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """Tests successful stock take completion."""
        # Create stock take
        from app.modules.stock_takes.models import StockTake, StockTakeItem

        stock_take = StockTake(
            user_id=test_items_batch[0].storage_location.created_by,
            organization_id=test_items_batch[0].storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='To finalize',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(stock_take)
        db_session.flush()

        # Add items
        for item in test_items_batch:
            stock_take_item = StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=item.id,
                item_name=item.name,
                system_quantity=item.quantity,
                counted_quantity=item.quantity,
            )
            db_session.add(stock_take_item)

        db_session.commit()

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == StockTakeStatus.COMPLETED.value
        assert data['progress_percent'] == 100.0

    def test_complete_stock_take_uncounted_items(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests completing with uncounted items."""
        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'uncounted items remaining' in response.json()['detail']['message']

    def test_complete_stock_take_partial_when_require_full_count_false(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """require_full_count=False must allow closing a partial count."""
        from app.modules.stock_takes.models import StockTake, StockTakeItem

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=test_storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='Partial count',
            status=StockTakeStatus.IN_PROGRESS,
            require_full_count=False,
        )
        db_session.add(stock_take)
        db_session.flush()

        for index, item in enumerate(test_items_batch):
            db_session.add(
                StockTakeItem(
                    stock_take_id=stock_take.id,
                    item_id=item.id,
                    item_name=item.name,
                    system_quantity=item.quantity,
                    counted_quantity=item.quantity if index == 0 else None,
                )
            )
        db_session.commit()

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': False},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == StockTakeStatus.COMPLETED.value
        assert data['not_counted'] == 4


@pytest.mark.integration
class TestStockTakeReport:
    """Tests for stock take report endpoint."""

    def test_get_stock_take_report(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Tests fetching stock take report."""
        response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/report', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['stock_take_id'] == str(test_stock_take.id)
        assert data['stock_take_name'] == test_stock_take.name
        assert 'total_items' in data
        assert 'discrepancies' in data
        assert 'all_items' in data
