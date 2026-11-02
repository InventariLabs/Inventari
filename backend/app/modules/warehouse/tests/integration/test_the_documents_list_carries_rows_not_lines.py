"""The documents list carries one summed row per document, not its lines.

A page of fifty completed documents was a megabyte: every document carried
every line, with its record, its product, its shelves and its prices, while
the list prints a sentence, a count and a progress bar. The row now carries
what the list shows — the count of the lines, what they planned and did per
unit, the first two of them, and the lines a module's column reads (those
that carry a module's fields) — and the document's own screen carries the
rest.

The search reads the same row set: a document is found by its number, its
references and partner, and the products named on its lines, each through
an index of its own.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus

pytestmark = pytest.mark.integration

URL = '/api/v1/warehouse/documents'


def _line(
    number: int,
    name: str,
    uom: Uom,
    planned: str,
    done: str,
    **extra: Any,
) -> DocumentLine:
    return DocumentLine(
        name=name,
        uom_id=uom.id,
        quantity=Decimal(planned),
        expected_quantity=Decimal(planned),
        done_quantity=Decimal(done),
        line_number=number,
        **extra,
    )


@pytest.fixture
def receipt(
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_uom_pcs: Uom,
    doc_uom_kg: Uom,
) -> Document:
    """A confirmed receipt of four lines in two units, half received."""
    doc = Document(
        organization_id=doc_org.id,
        type='IN',
        number='IN/2026/0417',
        status=DocumentStatus.CONFIRMED.value,
        partner_id=doc_partner.id,
        partner_snapshot={'name': 'Acme Supplies'},
        target_location_id=doc_target_location.id,
        created_by=doc_user.id,
    )
    doc.lines.extend(
        [
            _line(1, 'Hex bolt M6', doc_uom_pcs, '20', '20'),
            _line(2, 'Flat washer', doc_uom_pcs, '30', '10', batch_number='L-7'),
            _line(3, 'Grease', doc_uom_kg, '12.5', '0'),
            _line(
                4,
                'Cable tie',
                doc_uom_pcs,
                '5',
                '0',
                meta_data={'lot_certificates': {'number': 'C-1'}},
            ),
        ]
    )
    db_session.add(doc)
    db_session.commit()
    return doc


def _rows(
    client: TestClient, headers: dict[str, str], **params: Any
) -> list[dict[str, Any]]:
    response = client.get(URL, headers=headers, params=params)
    assert response.status_code == status.HTTP_200_OK, response.text
    items: list[dict[str, Any]] = response.json()['items']
    return items


class TestTheRow:
    def test_the_row_sums_the_lines_it_does_not_carry(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        receipt: Document,
    ) -> None:
        (row,) = _rows(client, doc_auth_headers)

        assert 'lines' not in row
        assert row['line_count'] == 4
        assert [
            (group['unit'], Decimal(group['planned']), Decimal(group['done']))
            for group in row['unit_progress']
        ] == [('pcs', Decimal('55'), Decimal('30')), ('kg', Decimal('12.5'), 0)]
        assert [line['name'] for line in row['first_lines']] == [
            'Hex bolt M6',
            'Flat washer',
        ]

    def test_a_module_reads_the_lines_that_carry_its_fields(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        receipt: Document,
    ) -> None:
        (row,) = _rows(client, doc_auth_headers)

        assert [
            (line['batch_number'], line['meta_data']) for line in row['module_lines']
        ] == [(None, {'lot_certificates': {'number': 'C-1'}})]

    def test_the_documents_own_screen_still_carries_every_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        receipt: Document,
    ) -> None:
        response = client.get(f'{URL}/{receipt.id}', headers=doc_auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()['lines']) == 4


class TestTheSearch:
    @pytest.mark.parametrize(
        'term',
        ['IN/2026/0417', '0417', 'Acme', 'washer', 'GREASE'],
    )
    def test_a_document_is_found_by_what_a_person_remembers(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        receipt: Document,
        term: str,
    ) -> None:
        rows = _rows(client, doc_auth_headers, search=term)

        assert [row['number'] for row in rows] == ['IN/2026/0417']

    def test_a_term_on_nothing_finds_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        receipt: Document,
    ) -> None:
        assert _rows(client, doc_auth_headers, search='Sprocket') == []

    def test_a_number_inside_another_type_is_not_a_match(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        receipt: Document,
    ) -> None:
        """``N/2026/0417`` sits inside ``IN/2026/0417`` but names another
        type's number; a term starting with a letter matches a whole code."""
        assert _rows(client, doc_auth_headers, search='N/2026/0417') == []
