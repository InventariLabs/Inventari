"""The three doors that create an asset land it in stock the same way.

Bulk create, POST /items and the spreadsheet import all write an asset
with Item.quantity = 1 — and the import alone used to turn the record's
own posting off, so an asset's stock stood behind it or not
depending on which door it entered through, and the reconciliation
report read that as a permanent mismatch. Every door now writes the
record, and beside it the movement that brought it onto the shelf.

The test builds its own org with ``stock_takes`` on. The posting used to
run only for organizations with a stock-consuming module; it now runs
for every organization, and the module stays here
as the ordinary shape of an equipment organization.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User

_SAMPLE_CSV = b'name,serial\nImported-1,SN-IMPORT-900\n'


@pytest.mark.integration
class TestEveryAssetDoorLandsInStock:
    @pytest.fixture
    def stock_org(self, h: ModuleTestHelper) -> Organization:
        return h.create_org(
            'Stock-Tracking Equipment Org',
            [
                'core',
                'items',
                'locations',
                'categories',
                'equipment',
                'stock_takes',
            ],
        )

    @pytest.fixture
    def stock_user(self, h: ModuleTestHelper, stock_org: Organization) -> User:
        return h.create_user(stock_org, email='stock-equipment@example.com')

    @pytest.fixture
    def stock_headers(self, h: ModuleTestHelper, stock_user: User) -> dict[str, str]:
        return h.get_auth_headers(stock_user)

    @pytest.fixture
    def stock_location(
        self,
        h: ModuleTestHelper,
        stock_org: Organization,
        stock_user: User,
    ) -> StorageLocation:
        storage_type = h.create_storage_type('IT Storage', 'IT_STOCK_EQ')
        return h.create_storage_location(
            stock_org, storage_type, stock_user, name='Stock Shelf A'
        )

    @pytest.fixture
    def stock_category(self, db_session: Session, stock_org: Organization) -> Category:
        category = Category(
            name='Equipment Stock Cat',
            organization_id=stock_org.id,
        )
        db_session.add(category)
        db_session.commit()
        return category

    def _import_asset(
        self,
        client: TestClient,
        stock_headers: dict[str, str],
        stock_location: StorageLocation,
        stock_category: Category,
    ) -> None:
        mapping = {'name': 'name', 'serial_number': 'serial'}
        resp = client.post(
            '/api/v1/equipment/import/execute',
            headers=stock_headers,
            files={'file': ('assets.csv', _SAMPLE_CSV, 'text/csv')},
            data={
                'mapping_json': json.dumps(mapping),
                'default_location_id': str(stock_location.id),
                'default_category_id': str(stock_category.id),
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['imported'] == 1

    def _bulk_asset(
        self,
        client: TestClient,
        stock_headers: dict[str, str],
        stock_location: StorageLocation,
        stock_category: Category,
    ) -> None:
        payload: dict[str, Any] = {
            'name': 'Bulk-1',
            'location_id': str(stock_location.id),
            'entries': [{'serial_number': 'SN-BULK-900'}],
        }
        resp = client.post(
            '/api/v1/equipment/items/bulk',
            headers=stock_headers,
            json=payload,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['created'] == 1

    def _api_asset(
        self,
        client: TestClient,
        stock_headers: dict[str, str],
        stock_location: StorageLocation,
        stock_category: Category,
    ) -> None:
        resp = client.post(
            '/api/v1/items',
            headers=stock_headers,
            json={
                'name': 'API-1',
                'location_id': str(stock_location.id),
                'quantity': 1,
                'serial_number': 'SN-API-900',
                'category_id': str(stock_category.id),
            },
        )
        assert resp.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), resp.text

    def test_import_bulk_and_api_end_with_the_same_stock(
        self,
        client: TestClient,
        stock_headers: dict[str, str],
        stock_location: StorageLocation,
        stock_category: Category,
        db_session: Session,
    ) -> None:
        self._import_asset(client, stock_headers, stock_location, stock_category)
        self._bulk_asset(client, stock_headers, stock_location, stock_category)
        self._api_asset(client, stock_headers, stock_location, stock_category)

        db_session.expire_all()
        assets = (
            db_session.query(Item)
            .filter(Item.organization_id == stock_location.organization_id)
            .filter(Item.name.in_(['Imported-1', 'Bulk-1', 'API-1']))
            .all()
        )
        assert len(assets) == 3

        for asset in assets:
            shelf = (
                db_session.query(ShelfRow)
                .filter(
                    ShelfRow.organization_id == asset.organization_id,
                    ShelfRow.product_template_id == asset.template_id,
                    ShelfRow.storage_location_id == asset.storage_location_id,
                )
                .one_or_none()
            )
            assert shelf is not None, (
                f'{asset.name}: no stock on the shelf behind the asset — '
                f'template_id={asset.template_id} '
                f'storage={asset.storage_location_id} '
                f'qty={asset.quantity}'
            )
            assert shelf.quantity == Decimal(asset.quantity), asset.name
            # And the ledger says how it got there: the movement onto the
            # shelf, whichever door the asset came through.
            arrived = (
                db_session.query(StockMove)
                .filter(
                    StockMove.organization_id == asset.organization_id,
                    StockMove.product_template_id == asset.template_id,
                    StockMove.to_location_id == asset.storage_location_id,
                )
                .all()
            )
            assert sum((move.quantity for move in arrived), Decimal('0')) == Decimal(
                asset.quantity
            ), f'{asset.name}: the ledger does not bring the asset onto the shelf'
