"""An asset's serial number has one home, whichever door it came through.

The serial number is stored in the core ``Item.serial_number`` column, whichever
door the asset came through. The core search, which the command palette asks,
reads that column, so a reader holding the device and typing the number off its
sticker finds the asset.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation


def _namespace(item: Item) -> dict[str, Any]:
    namespace: dict[str, Any] = (item.meta_data or {}).get('equipment', {})
    return namespace


@pytest.mark.integration
class TestEveryWritePathAgrees:
    """All three doors put the number in the column and nowhere else."""

    def test_batch_path(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json={
                'name': 'Dell Latitude 5540',
                'location_id': str(eq_storage_location.id),
                'category_id': str(eq_category.id),
                'entries': [{'serial_number': 'SN-BATCH-1'}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

        item = db_session.scalars(
            select(Item).where(Item.id == response.json()['items'][0])
        ).one()
        assert item.serial_number == 'SN-BATCH-1'
        assert 'serial_number' not in _namespace(item)

    def test_single_item_path(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        response = client.post(
            '/api/v1/items',
            headers=eq_auth_headers,
            json={
                'name': 'ThinkPad T14',
                'location_id': str(eq_storage_location.id),
                'category_id': str(eq_category.id),
                'quantity': 1,
                'serial_number': 'SN-SINGLE-1',
                'metadata': {'equipment': {'equipment_status': 'AVAILABLE'}},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

        item = db_session.scalars(
            select(Item).where(Item.id == response.json()['id'])
        ).one()
        assert item.serial_number == 'SN-SINGLE-1'
        assert 'serial_number' not in _namespace(item)

    def test_import_path(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        csv = b'name,serial\nMacBook Air,SN-IMPORT-1\n'
        response = client.post(
            '/api/v1/equipment/import/execute',
            headers=eq_auth_headers,
            files={'file': ('assets.csv', csv, 'text/csv')},
            data={
                'mapping_json': json.dumps({'name': 'name', 'serial_number': 'serial'}),
                'default_location_id': str(eq_storage_location.id),
                'default_category_id': str(eq_category.id),
            },
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['imported'] == 1

        db_session.expire_all()
        item = db_session.scalars(select(Item).where(Item.name == 'MacBook Air')).one()
        assert item.serial_number == 'SN-IMPORT-1'
        assert 'serial_number' not in _namespace(item)


@pytest.mark.integration
class TestTheNumberIsFindable:
    def test_core_search_finds_an_asset_by_its_serial_number(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        """What the command palette asks, with the number off the sticker."""
        client.post(
            '/api/v1/items',
            headers=eq_auth_headers,
            json={
                'name': 'Router MX-84',
                'location_id': str(eq_storage_location.id),
                'category_id': str(eq_category.id),
                'quantity': 1,
                'serial_number': 'SN-FIND-ME',
            },
        )

        response = client.get(
            '/api/v1/items?search=SN-FIND-ME', headers=eq_auth_headers
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        names = [row['name'] for row in response.json()['items']]
        assert names == ['Router MX-84']

    def test_a_row_written_before_the_move_keeps_its_number(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """The namespace is still read, so old rows do not lose identity."""
        assert eq_item.serial_number is None

        response = client.get('/api/v1/equipment/assets', headers=eq_auth_headers)
        assert response.status_code == status.HTTP_200_OK, response.text
        row = next(r for r in response.json()['items'] if r['id'] == str(eq_item.id))
        assert row['serial_number'] == 'SN-001'
