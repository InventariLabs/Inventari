"""A stub door asks for the permission its work requires.

Creating a product template is ``items:write`` work. Two documents doors
did it for a caller holding only ``warehouse:write``: quick-create founded
a stub template on the fly, and the opening-stock import founded one per
unmatched sheet row — the second with the decision hardcoded inside the
service, so no caller could even decline it. The equipment import already
shows the shape the tree agreed on: its own permission AND an explicit
``items:write``.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

MAPPING = {
    'name': 'Produkt',
    'sku': 'SKU',
    'barcode': 'EAN',
    'quantity': 'Ilość',
    'uom_symbol': 'Jm',
    'unit_price': 'Cena',
    'batch_number': 'Partia',
    'expiry_date': 'Ważne do',
}


@pytest.fixture
def docstubs_user(h: ModuleTestHelper, doc_org: Organization) -> User:
    """Documents writer without items:write — the measured role shape."""
    user = h.create_user(doc_org, email='docstubs@example.com', role='user')
    h.grant_permissions(user, ['warehouse:read', 'warehouse:write'])
    return user


def _sheet(rows: list[dict[str, Any]]) -> bytes:
    content: bytes = pd.DataFrame(rows).to_csv(index=False).encode()
    return content


def _row(name: str) -> dict[str, Any]:
    return {
        'Produkt': name,
        'SKU': None,
        'EAN': None,
        'Ilość': 1,
        'Jm': 'pcs',
        'Cena': '10.00',
        'Partia': None,
        'Ważne do': None,
    }


class TestAStubDoorAsksForItemsWrite:
    def test_quick_create_refuses_without_items_write(
        self,
        client: TestClient,
        docstubs_user: User,
        h: ModuleTestHelper,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            headers=h.get_auth_headers(docstubs_user),
            json={'name': 'Zaloz-mnie REV'},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_opening_stock_import_refuses_without_items_write(
        self,
        client: TestClient,
        docstubs_user: User,
        h: ModuleTestHelper,
        doc_target_location: StorageLocation,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/import/opening-stock',
            files={'file': ('stan.csv', _sheet([_row('Z arkusza REV')]), 'text/csv')},
            data={
                'mapping_json': json.dumps(MAPPING),
                'target_location_id': str(doc_target_location.id),
            },
            headers=h.get_auth_headers(docstubs_user),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_a_caller_with_items_write_still_creates(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
    ) -> None:
        writer = h.create_user(doc_org, email='writer@example.com', role='user')
        resp = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            headers=h.get_auth_headers(writer),
            json={'name': 'Zwykly zaloznik REV'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_the_stub_flag_belongs_to_the_caller(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_target_location: StorageLocation,
    ) -> None:
        """With items:write in hand, the caller may also decline the stubs."""
        writer = h.create_user(doc_org, email='decliner@example.com', role='user')
        resp = client.post(
            '/api/v1/warehouse/import/opening-stock',
            files={
                'file': (
                    'stan.csv',
                    _sheet([_row('Nie twórz mnie REV')]),
                    'text/csv',
                )
            },
            data={
                'mapping_json': json.dumps(MAPPING),
                'target_location_id': str(doc_target_location.id),
                'create_stubs_for_unmatched': 'false',
            },
            headers=h.get_auth_headers(writer),
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['stubs_created'] == 0
