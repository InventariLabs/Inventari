"""
Integration tests for the surplus item endpoint.

Verifies that POST /{stock_take_id}/items creates a surplus StockTakeItem
carrying the quantity the system already held for that item. "Surplus" means
the snapshot did not expect it here, not that there is none of it — see
``test_a_surplus_row_knows_what_was_there``.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient


@pytest.mark.integration
class TestSurplusItem:
    """Tests for adding surplus items to a stock take.

    Uses test_item (not in test_items_batch) to avoid 409 conflicts
    with items already created by the stock take fixture.
    """

    def test_post_items_creates_surplus_with_the_system_quantity_it_had(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        test_item: Any,
    ) -> None:
        """The row records what the system held, so the difference is real."""
        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'item_id': str(test_item.id),
                'counted_quantity': 15,
                'notes': 'Found extra in back room',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['item_id'] == str(test_item.id)
        assert Decimal(str(data['system_quantity'])) == test_item.quantity
        assert Decimal(data['counted_quantity']) == 15
        assert data['notes'] == 'Found extra in back room'
        assert data['is_discrepancy'] == 1  # 15 != 0

    def test_post_items_counting_what_the_system_held_is_no_discrepancy(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        test_item: Any,
        db_session: Session,
    ) -> None:
        """Nothing on the system and nothing on the shelf agree with each other."""
        test_item.quantity = Decimal('0')
        db_session.commit()

        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'item_id': str(test_item.id),
                'counted_quantity': 0,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert Decimal(data['system_quantity']) == 0
        assert Decimal(data['counted_quantity']) == 0
        assert data['is_discrepancy'] == 0

    def test_post_items_rejects_unknown_item(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """POST must return 404 for non-existent item."""
        from uuid import uuid4

        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'item_id': str(uuid4()),
                'counted_quantity': 5,
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_post_items_requires_item_id(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """POST must reject payload without item_id."""
        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'counted_quantity': 5,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_post_items_requires_counted_quantity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        test_item: Any,
    ) -> None:
        """POST must reject payload without counted_quantity."""
        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'item_id': str(test_item.id),
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_post_items_rejects_duplicate(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        test_item: Any,
    ) -> None:
        """POST must reject adding same item twice."""
        # First add — should succeed
        response1 = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'item_id': str(test_item.id),
                'counted_quantity': 5,
            },
        )
        assert response1.status_code == status.HTTP_201_CREATED

        # Second add — should conflict
        response2 = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'item_id': str(test_item.id),
                'counted_quantity': 10,
            },
        )
        assert response2.status_code == status.HTTP_409_CONFLICT

    def test_post_items_rejects_completed_stock_take(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_stock_take: Any,
        test_item: Any,
    ) -> None:
        """POST must reject adding items to a completed stock take."""
        from app.modules.stock_takes.models import StockTakeStatus

        # Complete the stock take
        test_stock_take.status = StockTakeStatus.COMPLETED
        db_session.commit()

        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={
                'item_id': str(test_item.id),
                'counted_quantity': 5,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
