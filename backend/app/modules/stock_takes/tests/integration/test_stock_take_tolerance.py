"""
Integration tests for tolerance_percent enforcement.

Verifies that apply_item_count honors tolerance_percent from StockTake,
flagging discrepancies only when the difference exceeds the threshold.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus


@pytest.mark.integration
class TestTolerancePercent:
    """Tests for tolerance-based discrepancy detection."""

    def test_discrepancy_within_tolerance_not_flagged(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """Difference within tolerance should NOT be flagged as discrepancy."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='Tolerance Test',
            status=StockTakeStatus.IN_PROGRESS,
            tolerance_percent=10,  # 10% tolerance
        )
        db_session.add(stock_take)
        db_session.flush()

        # Item with system_quantity=10, counted=10.5 (5% diff — within 10% tolerance)
        item = test_items_batch[0]
        stock_take_item = StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=10,
            counted_quantity=None,
        )
        db_session.add(stock_take_item)
        db_session.commit()

        # Count via API
        items_response = client.get(
            f'/api/v1/stock-takes/{stock_take.id}/items',
            headers=auth_headers,
        )
        items = items_response.json()['items']
        sti_id = items[0]['id']

        response = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/items/{sti_id}/count',
            headers=auth_headers,
            json={'counted_quantity': 10.5},  # 5% diff
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_discrepancy'] == 0, (
            'Should not flag discrepancy within tolerance'
        )

    def test_discrepancy_above_tolerance_flagged(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """Difference above tolerance should be flagged as discrepancy."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='Tolerance Test 2',
            status=StockTakeStatus.IN_PROGRESS,
            tolerance_percent=5,  # 5% tolerance
        )
        db_session.add(stock_take)
        db_session.flush()

        item = test_items_batch[0]
        stock_take_item = StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=10,
            counted_quantity=None,
        )
        db_session.add(stock_take_item)
        db_session.commit()

        items_response = client.get(
            f'/api/v1/stock-takes/{stock_take.id}/items',
            headers=auth_headers,
        )
        items = items_response.json()['items']
        sti_id = items[0]['id']

        response = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/items/{sti_id}/count',
            headers=auth_headers,
            json={'counted_quantity': 12},  # 20% diff — above 5% tolerance
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_discrepancy'] == 1, 'Should flag discrepancy above tolerance'

    def test_zero_tolerance_equivalent_to_exact_match(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """Zero tolerance should require exact match (same as no tolerance)."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='Zero Tolerance',
            status=StockTakeStatus.IN_PROGRESS,
            tolerance_percent=0,
        )
        db_session.add(stock_take)
        db_session.flush()

        item = test_items_batch[0]
        stock_take_item = StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=10,
            counted_quantity=None,
        )
        db_session.add(stock_take_item)
        db_session.commit()

        items_response = client.get(
            f'/api/v1/stock-takes/{stock_take.id}/items',
            headers=auth_headers,
        )
        items = items_response.json()['items']
        sti_id = items[0]['id']

        # Count with 0.1 diff — should be flagged with zero tolerance
        response = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/items/{sti_id}/count',
            headers=auth_headers,
            json={'counted_quantity': 10.1},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_discrepancy'] == 1, 'Zero tolerance should flag any difference'

    def test_no_tolerance_preserves_exact_match_behavior(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """Without tolerance, exact match should not flag discrepancy."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='No Tolerance',
            status=StockTakeStatus.IN_PROGRESS,
            tolerance_percent=None,
        )
        db_session.add(stock_take)
        db_session.flush()

        item = test_items_batch[0]
        stock_take_item = StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=10,
            counted_quantity=None,
        )
        db_session.add(stock_take_item)
        db_session.commit()

        items_response = client.get(
            f'/api/v1/stock-takes/{stock_take.id}/items',
            headers=auth_headers,
        )
        items = items_response.json()['items']
        sti_id = items[0]['id']

        response = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/items/{sti_id}/count',
            headers=auth_headers,
            json={'counted_quantity': 10},  # exact match
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_discrepancy'] == 0, 'Exact match should not be a discrepancy'
