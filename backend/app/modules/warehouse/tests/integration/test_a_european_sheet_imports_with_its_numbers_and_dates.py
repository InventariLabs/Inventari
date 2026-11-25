"""A sheet written the way a European Excel saves it imports with what it holds.

Excel in Poland, Germany, France, Spain and Portugal writes a semicolon
between columns, a comma inside a number, a space or a dot between
thousands, a currency word after a price, and the day before the month. The
importer must neither refuse a decimal nor swap the day and month of a date
whose day is 12 or less — an expiry term moved by months with the row counted
as imported. Opening stock and the document lines read the sheet through the
same reader as every other door, so what the sheet says is what the lines
hold.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.storage_location import StorageLocation

MAPPING = {
    'name': 'Produkt',
    'quantity': 'Ilość',
    'unit_price': 'Cena',
    'expiry_date': 'Ważne do',
}

SHEET = (
    'Produkt;Ilość;Cena;Ważne do\n'
    'Mleko;12,5;1 289,00 zł;05.11.2026\n'
    'Ser;1 200;4,50 zł;03/12/2025\n'
    'Masło;1.250,5;€ 7,49;28.02.2025\n'
).encode('cp1250')


def _read_lines(
    client: TestClient, headers: dict[str, str], sheet: bytes, language: str
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/import/lines',
        files={'file': ('arkusz.csv', sheet, 'text/csv')},
        data={'mapping_json': json.dumps(MAPPING), 'type': 'IN'},
        headers={**headers, 'Accept-Language': language},
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


@pytest.mark.integration
class TestAEuropeanSheetImportsWithItsNumbersAndDates:
    def test_the_document_lines_hold_the_numbers_and_dates_the_sheet_wrote(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        body = _read_lines(client, doc_auth_headers, SHEET, 'pl')

        assert (body['imported'], body['failed']) == (3, 0), body['errors']
        lines = {line['name']: line for line in body['lines']}
        assert Decimal(lines['Mleko']['quantity']) == Decimal('12.5')
        assert Decimal(lines['Mleko']['unit_price']) == Decimal('1289.00')
        assert Decimal(lines['Ser']['quantity']) == Decimal('1200')
        assert Decimal(lines['Masło']['quantity']) == Decimal('1250.5')
        assert Decimal(lines['Masło']['unit_price']) == Decimal('7.49')
        # 5 November and 3 December, not 11 May and 12 March.
        assert lines['Mleko']['expiry_date'] == date(2026, 11, 5).isoformat()
        assert lines['Ser']['expiry_date'] == date(2025, 12, 3).isoformat()
        assert lines['Masło']['expiry_date'] == date(2025, 2, 28).isoformat()

    def test_an_all_ambiguous_column_follows_the_importers_language(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        sheet = 'Produkt;Ilość;Cena;Ważne do\nMleko;1;1;05.11.2026\n'.encode()

        polish = _read_lines(client, doc_auth_headers, sheet, 'pl')
        english = _read_lines(client, doc_auth_headers, sheet, 'en')

        assert polish['lines'][0]['expiry_date'] == '2026-11-05'
        assert english['lines'][0]['expiry_date'] == '2026-05-11'

    def test_an_unreadable_date_refuses_the_row_instead_of_dropping_it(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        sheet = (
            'Produkt;Ilość;Cena;Ważne do\nMleko;1;1;koniec marca\nSer;1;1;05.11.2026\n'
        ).encode()

        body = _read_lines(client, doc_auth_headers, sheet, 'pl')

        assert (body['imported'], body['failed']) == (1, 1)
        assert body['errors'][0]['row'] == 1
        assert 'koniec marca' in body['errors'][0]['error']
        assert [line['name'] for line in body['lines']] == ['Ser']

    def test_a_value_that_is_not_a_number_is_still_refused_with_its_cell(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        sheet = 'Produkt;Ilość;Cena;Ważne do\nMleko;1;tanio;\n'.encode()

        body = _read_lines(client, doc_auth_headers, sheet, 'pl')

        assert body['imported'] == 0
        assert 'tanio' in body['errors'][0]['error']

    def test_opening_stock_reads_the_same_sheet(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/import/opening-stock',
            files={'file': ('arkusz.csv', SHEET, 'text/csv')},
            data={
                'mapping_json': json.dumps(MAPPING),
                'target_location_id': str(doc_target_location.id),
            },
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body['imported'], body['failed']) == (3, 0), body['errors']
        doc = client.get(
            f'/api/v1/warehouse/documents/{body["document_id"]}',
            headers=doc_auth_headers,
        ).json()
        lines = {line['name']: line for line in doc['lines']}
        assert Decimal(lines['Mleko']['expected_quantity']) == Decimal('12.5')
        assert lines['Mleko']['expiry_date'] == '2026-11-05'
        assert lines['Ser']['expiry_date'] == '2025-12-03'
