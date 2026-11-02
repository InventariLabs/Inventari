"""Opening stock lands as one draft receipt.

The moment a company leaves its spreadsheet is the moment it types its
whole stock into the app, one receipt line at a time. A sheet with a
product, a quantity, a price and, when there is one, a lot and an expiry
date becomes one draft receipt flagged as opening stock: every row finds
its product by barcode, SKU or name, or founds one on the way, so that
posting the draft puts each price into the cost layers. A row the importer
cannot read is reported with its reason and holds nothing else up.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.stock_lot import StockLot
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document

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


def _row(name: str | None, qty: Any, price: str, **extra: Any) -> dict[str, Any]:
    row = {
        'Produkt': name,
        'SKU': None,
        'EAN': None,
        'Ilość': qty,
        'Jm': 'pcs',
        'Cena': price,
        'Partia': None,
        'Ważne do': None,
    }
    row.update(extra)
    return row


def _upload(
    client: TestClient,
    headers: dict[str, str],
    rows: list[dict[str, Any]],
    location: StorageLocation,
) -> Any:
    content = pd.DataFrame(rows).to_csv(index=False).encode()
    return client.post(
        '/api/v1/warehouse/import/opening-stock',
        files={'file': ('stan.csv', content, 'text/csv')},
        data={
            'mapping_json': json.dumps(MAPPING),
            'target_location_id': str(location.id),
        },
        headers=headers,
    )


@pytest.mark.integration
class TestOpeningStockLandsAsOneDraftReceipt:
    def test_fifty_rows_become_one_draft_and_three_are_reported(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        by_barcode = h.create_template(doc_org, name='Mąka', barcode='5900000000017')
        by_sku = h.create_template(doc_org, name='Cukier', sku='CUK-1')
        by_name = h.create_template(doc_org, name='Sól kamienna')

        rows = [
            _row(
                'Whatever the sheet says',
                10,
                '12.50',
                EAN='5900000000017',
                Partia='LOT-A',
                **{'Ważne do': '2027-12-31'},
            ),
            _row('Cukier biały', 4, '3.20', SKU='cuk-1'),
            _row('sól kamienna', 7, '1.10'),
        ]
        rows += [_row(f'Nowy produkt {i}', i, f'{i}.00') for i in range(1, 48)]
        rows += [
            _row(None, 5, '1.00'),
            _row('Zła ilość', 'dużo', '1.00'),
            _row('Zła cena', 5, 'tanio'),
        ]
        assert len(rows) == 53

        resp = _upload(client, doc_auth_headers, rows, doc_target_location)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body['total'], body['imported'], body['failed']) == (53, 50, 3)
        # The row as the import preview numbers it: data rows from 1, the
        # header not counted. One numbering for the whole import screen —
        # the preview the reader picks the mapping on, and the refusals the
        # result screen lists. It used to count the header as row 1, so a
        # refusal pointed one row past the row it meant.
        assert [e['row'] for e in body['errors']] == [51, 52, 53]
        assert 'name' in body['errors'][0]['error'].lower()
        assert 'dużo' in body['errors'][1]['error']
        assert 'tanio' in body['errors'][2]['error']
        assert body['matched'] == 50 and body['unmatched'] == 0
        assert body['stubs_created'] == 47

        doc = db_session.get(Document, body['document_id'])
        assert doc is not None
        assert (doc.type, doc.status, doc.is_opening) == ('IN', 'DRAFT', True)
        assert doc.target_location_id == doc_target_location.id
        assert doc.partner_id is None
        assert len(doc.lines) == 50
        assert all(line.product_template_id is not None for line in doc.lines)
        templates = {line.product_template_id for line in doc.lines}
        assert {by_barcode.id, by_sku.id, by_name.id} <= templates
        assert doc.number == body['number']
        # 10 x 12.50 + 4 x 3.20 + 7 x 1.10 + sum(i x i for i in 1..47)
        assert doc.total_net == Decimal('35865.50')

        shown = client.get(
            f'/api/v1/warehouse/documents/{doc.id}', headers=doc_auth_headers
        )
        assert shown.status_code == 200
        assert shown.json()['is_opening'] is True

    def test_posting_the_draft_puts_the_sheet_prices_into_the_cost_layers(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        flour = h.create_template(doc_org, name='Mąka', barcode='5900000000024')
        rows = [
            _row('Mąka', 10, '12.50', EAN='5900000000024', Partia='LOT-7'),
            _row('Produkt bez kodu', 3, '0.80'),
        ]
        body = _upload(client, doc_auth_headers, rows, doc_target_location).json()
        doc_id = body['document_id']

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == 200, confirmed.text
        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == 200, completed.text

        layers = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id == doc_org.id,
                StockValuationLayer.direction == 'IN',
            )
        ).all()
        costs = {
            layer.product_template_id: Decimal(layer.unit_cost) for layer in layers
        }
        assert costs[flour.id] == Decimal('12.50')
        assert Decimal('0.80') in costs.values()
        assert len(costs) == 2

        lot = db_session.scalar(
            select(StockLot).where(
                StockLot.product_template_id == flour.id, StockLot.name == 'LOT-7'
            )
        )
        assert lot is not None

    def test_a_failure_after_the_lines_are_read_leaves_no_draft_behind(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The whole import is one unit of work, not two transactions.

        The failure is forced in the step right after the lines were built
        — the one that used to run behind the importer's own commit. With
        that commit there, the draft and its lines were already in the
        database when the request answered the error: revert
        ``import_lines_from_dataframe`` to commit and the last assertion
        finds the row it must not.
        """
        from app.modules.warehouse import opening_stock_service

        async def _refuse_the_tax_step(*args: Any, **kwargs: Any) -> None:
            raise ValueError('forced failure after the lines were imported')

        monkeypatch.setattr(
            opening_stock_service, '_apply_line_tax_rates', _refuse_the_tax_step
        )

        resp = _upload(
            client,
            doc_auth_headers,
            [_row('Mąka', 10, '12.50')],
            doc_target_location,
        )
        assert resp.status_code == 400, resp.text
        assert (
            db_session.scalar(
                select(Document).where(
                    Document.organization_id == doc_org.id, Document.is_opening
                )
            )
            is None
        )

    def test_a_sheet_nothing_can_be_read_from_leaves_no_draft_behind(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        rows = [_row(None, 1, '1.00'), _row('X', 'abc', '1.00')]
        resp = _upload(client, doc_auth_headers, rows, doc_target_location)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['document_id'] is None
        assert (body['imported'], body['failed']) == (0, 2)
        assert (
            db_session.scalar(
                select(Document).where(
                    Document.organization_id == doc_org.id, Document.is_opening
                )
            )
            is None
        )
