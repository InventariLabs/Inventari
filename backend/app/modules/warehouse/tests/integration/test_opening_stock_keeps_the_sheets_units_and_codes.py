"""Opening stock keeps what the sheet says: its units and its codes.

A row in cartons or litres used to found a product kept in pieces while its
line stayed in the sheet's unit, so the draft could not be opened. The row
now founds a product kept in the unit it was written in, a row that names a
unit an existing product cannot take is refused by row, the codes the sheet
carries become the product's own, and the answer counts what was found
apart from what was founded.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document

MAPPING = {
    'name': 'Produkt',
    'sku': 'SKU',
    'barcode': 'EAN',
    'quantity': 'Ilość',
    'uom_symbol': 'Jm',
}


def _row(name: str, qty: Any, unit: str | None, **extra: Any) -> dict[str, Any]:
    return {
        'Produkt': name,
        'SKU': None,
        'EAN': None,
        'Ilość': qty,
        'Jm': unit,
        **extra,
    }


def _upload(
    client: TestClient,
    headers: dict[str, str],
    rows: list[dict[str, Any]],
    location: StorageLocation,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/import/opening-stock',
        files={
            'file': ('stan.csv', pd.DataFrame(rows).to_csv(index=False), 'text/csv')
        },
        data={
            'mapping_json': json.dumps(MAPPING),
            'target_location_id': str(location.id),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    found = db.scalars(
        select(ProductTemplate).where(
            ProductTemplate.organization_id == org.id, ProductTemplate.name == name
        )
    ).one()
    db.refresh(found)
    return found


@pytest.mark.integration
class TestOpeningStockKeepsTheSheetsUnitsAndCodes:
    def test_a_row_in_cartons_or_litres_founds_a_product_in_that_unit(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        body = _upload(
            client,
            doc_auth_headers,
            [
                _row('Copy paper', 50, 'box'),
                _row('Olive oil, extra virgin 5 L', 28, 'L'),
                _row('Plain stub', 3, None),
            ],
            doc_target_location,
        )
        assert (body['imported'], body['failed']) == (3, 0)

        assert _template(db_session, doc_org, 'Copy paper').uom_id == (
            h.get_uom('box').id
        )
        assert _template(db_session, doc_org, 'Olive oil, extra virgin 5 L').uom_id == (
            h.get_uom('l').id
        )
        # A row that names no unit still founds a product kept in pieces.
        assert _template(db_session, doc_org, 'Plain stub').uom_id == (
            h.get_uom('pcs').id
        )

        shown = client.get(
            f'/api/v1/warehouse/documents/{body["document_id"]}',
            headers=doc_auth_headers,
        )
        assert shown.status_code == 200, shown.text
        assert all(
            line['unit_conversion_error'] is None for line in shown.json()['lines']
        )

    def test_a_row_in_a_unit_an_existing_product_cannot_take_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        h.create_template(doc_org, name='Stapler', uom_id=h.get_uom('pcs').id)

        body = _upload(
            client,
            doc_auth_headers,
            [_row('Stapler', 4, 'kg'), _row('Stapler', 5, 'pcs')],
            doc_target_location,
        )

        assert (body['imported'], body['failed']) == (1, 1)
        refused = body['errors'][0]
        assert refused['row'] == 1
        assert 'kg' in refused['error'] and 'pcs' in refused['error']
        shown = client.get(
            f'/api/v1/warehouse/documents/{body["document_id"]}',
            headers=doc_auth_headers,
        )
        assert shown.status_code == 200, shown.text
        assert len(shown.json()['lines']) == 1

    def test_a_founded_product_keeps_the_rows_sku_and_barcode(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        _upload(
            client,
            doc_auth_headers,
            [_row('Desk lamp', 6, 'pcs', SKU='LAMP-01', EAN='5900000000123')],
            doc_target_location,
        )

        lamp = _template(db_session, doc_org, 'Desk lamp')
        assert (lamp.sku, lamp.barcode) == ('LAMP-01', '5900000000123')

    def test_found_founded_and_failed_add_up_to_the_rows_read(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        h.create_template(doc_org, name='Stapler', sku='STA-1')
        body = _upload(
            client,
            doc_auth_headers,
            [
                _row('Stapler', 2, 'pcs'),
                _row('New one', 3, 'pcs'),
                _row('New two', 4, 'pcs'),
                _row('Bad', 'many', 'pcs'),
            ],
            doc_target_location,
        )

        assert body['matched'] == 1
        assert body['stubs_created'] == 2
        assert body['failed'] == 1
        assert body['matched'] + body['stubs_created'] + body['failed'] == body['total']
        assert body['unmatched'] == 0
        doc = db_session.get(Document, body['document_id'])
        assert doc is not None and len(doc.lines) == 3


@pytest.mark.integration
class TestADocumentWhoseLineUnitStopsConvertingStillOpens:
    def test_the_detail_marks_the_line_instead_of_refusing_the_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        body = _upload(
            client,
            doc_auth_headers,
            [_row('Copy paper', 50, 'box'), _row('Pens', 10, 'pcs')],
            doc_target_location,
        )
        # The product is later moved to a unit the line's unit cannot become.
        paper = _template(db_session, doc_org, 'Copy paper')
        paper.uom_id = h.get_uom('kg').id
        db_session.commit()

        shown = client.get(
            f'/api/v1/warehouse/documents/{body["document_id"]}',
            headers=doc_auth_headers,
        )

        assert shown.status_code == 200, shown.text
        lines = {line['name']: line for line in shown.json()['lines']}
        assert 'box' in lines['Copy paper']['unit_conversion_error']
        assert 'kg' in lines['Copy paper']['unit_conversion_error']
        assert lines['Pens']['unit_conversion_error'] is None
