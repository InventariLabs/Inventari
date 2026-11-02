"""A scan finds a line that names its stock record but not its product.

The document scanner builds a line from the record the picker held in the
hand, so the line carries ``item_id`` alone. Picking compared the scanned
product with the line's own ``product_template_id`` only, so scanning exactly
the right product answered "not in the document" and sent the picker down the
manual paths, while the session already knew the line's product through the
record. Receiving fell back to the line's stored barcode compared as a raw
string, which a UPC-A stored on the line never matched against the EAN-13 the
catalogue lookup had normalized.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import DocumentLine


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    body: dict[str, Any],
) -> str:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id


def _start(client: TestClient, headers: dict[str, str], doc_id: str, kind: str) -> str:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/{kind}/start', headers=headers
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


@pytest.mark.integration
class TestScanMatchesThroughTheItem:
    def test_a_picking_scan_finds_a_line_that_carries_only_its_item(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 3}],
            },
        )
        session_id = _start(client, doc_auth_headers, doc_id, 'picking')

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 3},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()
        assert data['status'] == 'picked'
        assert data['picked_quantity'] == 3.0
        assert data['session_complete'] is True

    def test_a_picking_scan_of_another_product_is_still_not_in_the_document(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_stock_item: Item,
    ) -> None:
        other = h.create_template(
            doc_org, name='Other product', barcode='4006381333931'
        )
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 3}],
            },
        )
        session_id = _start(client, doc_auth_headers, doc_id, 'picking')

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': other.barcode, 'quantity': 1},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'not_in_document'

    def test_a_receiving_scan_finds_a_line_that_carries_only_its_item(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 2}],
            },
        )
        session_id = _start(client, doc_auth_headers, doc_id, 'receiving')

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'received'

    def test_a_receiving_scan_compares_the_stored_barcode_in_its_normalized_form(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template = h.create_template(doc_org, name='Imported', barcode='0012345678905')
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'name': 'Typed by hand',
                        'barcode': template.barcode,
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        # A UPC-A written on the line by hand: the catalogue lookup turns the
        # scan into the EAN-13 form, so the raw comparison never matched.
        db_session.execute(
            update(DocumentLine)
            .where(DocumentLine.document_id == uuid.UUID(doc_id))
            .values(barcode='012345678905', product_template_id=None)
        )
        db_session.commit()
        session_id = _start(client, doc_auth_headers, doc_id, 'receiving')

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': template.barcode, 'quantity': 2},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'received'
