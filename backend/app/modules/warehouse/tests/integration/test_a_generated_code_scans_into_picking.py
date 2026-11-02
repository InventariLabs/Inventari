"""A product given an internal code on its form is picked by scanning that code.

The code the product form generates is printed on the product's label; the
picker scans the label, and the scan has to land on the product's line
through the same resolver every scan door uses.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation


def _generated_code(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        '/api/v1/items/product-templates/generate-barcode', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(str, resp.json()['barcode'])


@pytest.mark.integration
class TestGeneratedCodeScansIntoPicking:
    def test_a_picking_scan_of_the_generated_code_picks_the_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_stock_item: Item,
    ) -> None:
        code = _generated_code(client, doc_auth_headers)
        saved = client.put(
            f'/api/v1/items/{doc_stock_item.id}',
            headers=doc_auth_headers,
            json={'barcode': code},
        )
        assert saved.status_code == status.HTTP_200_OK, saved.text

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 2}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        started = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert started.status_code == status.HTTP_201_CREATED, started.text

        scan = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{started.json()["id"]}/scan',
            headers=doc_auth_headers,
            json={'barcode': code, 'quantity': 2},
        )

        assert scan.status_code == status.HTTP_200_OK, scan.text
        assert scan.json()['status'] == 'picked'
        assert scan.json()['picked_quantity'] == 2.0
