"""
Integration tests for the bulk count mapping fix.

Verifies that bulk_count_items_and_commit maps updates by StockTakeItem.id
rather than array index, preventing data corruption when DB order differs.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient


@pytest.mark.integration
class TestBulkCountMapping:
    """Tests for bulk count item_id-based mapping."""

    def test_bulk_count_maps_by_item_id_not_index(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_stock_take: Any,
    ) -> None:
        """Bulk count must map updates by item_id, not array position."""
        # Get stock take items
        items_response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
        )
        assert items_response.status_code == status.HTTP_200_OK
        items = items_response.json()['items']
        assert len(items) >= 2

        # Pick two items and reverse their order in payload
        first_item = items[0]
        second_item = items[1]

        # Count them in REVERSE order: second item gets first_item's quantity and vice versa
        payload = [
            {
                'item_id': second_item['id'],
                'counted_quantity': 100,
                'notes': 'second item counted',
            },
            {
                'item_id': first_item['id'],
                'counted_quantity': 200,
                'notes': 'first item counted',
            },
        ]

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/bulk-count',
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify each item got its OWN quantity, not the other's
        items_after = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
        ).json()['items']

        first_after = next(i for i in items_after if i['id'] == first_item['id'])
        second_after = next(i for i in items_after if i['id'] == second_item['id'])

        assert Decimal(first_after['counted_quantity']) == 200
        assert first_after['notes'] == 'first item counted'
        assert Decimal(second_after['counted_quantity']) == 100
        assert second_after['notes'] == 'second item counted'

    def test_bulk_count_ignores_unknown_item_id(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Bulk count must reject unknown item_id with 400."""
        from uuid import uuid4

        payload = [
            {
                'item_id': str(uuid4()),
                'counted_quantity': 50,
            },
        ]

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/bulk-count',
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'not found' in response.json()['detail']['message'].lower()

    def test_bulk_count_requires_item_id(
        self, client: TestClient, auth_headers: dict[str, str], test_stock_take: Any
    ) -> None:
        """Bulk count must reject payload without item_id."""
        payload = [
            {
                'counted_quantity': 50,
            },
        ]

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/bulk-count',
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'item_id' in response.json()['detail']['message'].lower()

    def test_bulk_count_preserves_quantities_when_db_order_differs(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_stock_take: Any,
    ) -> None:
        """Ensure quantities are correctly mapped even if items are stored in different order."""
        # Get items
        items_response = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
        )
        items = items_response.json()['items']

        # Build payload with distinct quantities for each item
        payload = []
        for idx, item in enumerate(items):
            payload.append(
                {
                    'item_id': item['id'],
                    'counted_quantity': (idx + 1) * 10,  # 10, 20, 30, ...
                }
            )

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/bulk-count',
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify each item has its specific quantity
        items_after = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
        ).json()['items']

        for idx, item in enumerate(items):
            matching = next(i for i in items_after if i['id'] == item['id'])
            assert Decimal(matching['counted_quantity']) == (idx + 1) * 10, (
                f'Item {item["id"]} expected {(idx + 1) * 10}, got {matching["counted_quantity"]}'
            )
