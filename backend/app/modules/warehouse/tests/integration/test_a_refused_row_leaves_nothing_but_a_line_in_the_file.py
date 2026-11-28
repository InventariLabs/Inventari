"""A refused document row is counted once, leaves no line and comes back in a file.

Opening stock and the line import answer with every refused row in the
uploaded format; corrected and uploaded alone, the file adds what was
missing. A row refused while its product is being founded leaves nothing on
the draft, and the draft's line numbers stay unique.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from uuid import UUID

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.import_sheet import read_rows
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import DocumentLine

MAPPING = {'name': 'Product', 'sku': 'SKU', 'quantity': 'Qty'}


def _sheet(rows: list[tuple[str, str, object]]) -> str:
    frame = pd.DataFrame(rows, columns=['Product', 'SKU', 'Qty'])
    return str(frame.to_csv(index=False))


def _opening(
    client: TestClient, headers: dict[str, str], sheet: str, location: StorageLocation
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/import/opening-stock',
        files={'file': ('stock.csv', sheet, 'text/csv')},
        data={
            'mapping_json': json.dumps(MAPPING),
            'target_location_id': str(location.id),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _refused(body: dict[str, Any]) -> pd.DataFrame:
    answer = body['refused_file']
    return read_rows(base64.b64decode(answer['content_base64']), answer['filename'])


def _lines(db: Session, document_id: str) -> list[DocumentLine]:
    return list(
        db.scalars(
            select(DocumentLine)
            .where(DocumentLine.document_id == UUID(document_id))
            .order_by(DocumentLine.line_number)
        )
    )


@pytest.mark.integration
class TestARefusedRowLeavesNothingButALineInTheFile:
    @pytest.mark.parametrize(
        ('name', 'sku'),
        [
            ('Long code', 'X' * 63),
            # Past the product's name column: refused only when the product is
            # being founded, after the line has been read.
            ('N' * 300, 'LONG-NAME'),
        ],
    )
    def test_a_row_refused_while_founding_its_product_is_counted_once(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        name: str,
        sku: str,
    ) -> None:
        sheet = _sheet([(name, sku, 1), ('Fine', 'FINE-1', 2), ('Also', 'FINE-2', 3)])

        body = _opening(client, doc_auth_headers, sheet, doc_target_location)

        assert (body['total'], body['imported'], body['failed']) == (3, 2, 1), body
        lines = _lines(db_session, body['document_id'])
        assert [(line.line_number, line.name) for line in lines] == [
            (1, 'Fine'),
            (2, 'Also'),
        ]
        assert all(line.product_template_id for line in lines)
        assert not db_session.scalars(
            select(ProductTemplate).where(ProductTemplate.sku == sku)
        ).first()

    def test_opening_stock_hands_the_refused_rows_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        sheet = _sheet([('Fine', 'FINE-1', 2), ('Broken', 'BR-1', 'many')])
        body = _opening(client, doc_auth_headers, sheet, doc_target_location)
        frame = _refused(body)
        assert body['refused_file']['filename'] == 'stock-refused.csv'
        assert list(frame['Product']) == ['Broken']
        assert 'many' in frame['Reason refused'][0]

        frame['Qty'] = '4'
        fixed = _opening(
            client, doc_auth_headers, frame.to_csv(index=False), doc_target_location
        )

        assert (fixed['imported'], fixed['failed']) == (1, 0), fixed
        assert fixed['refused_file'] is None

    def test_document_lines_hand_the_refused_rows_back(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        draft = _opening(
            client,
            doc_auth_headers,
            _sheet([('Fine', 'FINE-1', 2)]),
            doc_target_location,
        )
        url = f'/api/v1/warehouse/documents/{draft["document_id"]}/import-paste'

        def paste(text: str) -> dict[str, Any]:
            resp = client.post(
                url,
                json={'text': text, 'mapping_json': MAPPING},
                headers=doc_auth_headers,
            )
            assert resp.status_code == 200, resp.text
            answer: dict[str, Any] = resp.json()
            return answer

        body = paste('Product\tSKU\tQty\nFine\tFINE-1\t1\nFine\tFINE-1\t-3\n')

        assert (body['imported'], body['failed']) == (1, 1), body
        assert body['refused_file']['filename'] == 'pasted-rows-refused.csv'
        frame = _refused(body)
        assert list(frame['Qty']) == ['-3']

        frame['Qty'] = '3'
        fixed = paste(frame.to_csv(index=False, sep='\t'))
        assert (fixed['imported'], fixed['failed']) == (1, 0), fixed
        assert [line.quantity for line in _lines(db_session, draft['document_id'])] == [
            2,
            1,
            3,
        ]
