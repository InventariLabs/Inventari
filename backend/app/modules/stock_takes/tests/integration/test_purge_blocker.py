"""the stock_takes module vetoes purges of counted items.

An archived item that appears on any stock-take line is counting evidence —
purging it would CASCADE-delete the line and destroy the record. The purge
must return 409 with a structured ``stock_take_items`` blocker.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


class TestStockTakesPurgeBlocker:
    def test_stock_take_line_blocks_purge_with_structured_blockers(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_item: Item,
        test_storage_location: StorageLocation,
    ) -> None:
        """An item counted in a stock take must not be permanently deleted."""
        # Create a take over the item's location — it auto-includes the item.
        resp = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Purge Blocker Take',
                'location_id': str(test_storage_location.id),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        take_id = resp.json()['id']

        # Archive first — the blocker must not affect the soft delete.
        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
        assert resp.status_code in (200, 204)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        body = resp.json()['detail']
        blocks = body['blocks']
        stock = [b for b in blocks if b['type'] == 'stock_take_items']
        assert stock, f'expected stock_take_items blocker, got {blocks}'
        assert stock[0]['count'] >= 1
        assert take_id in stock[0]['ids']
