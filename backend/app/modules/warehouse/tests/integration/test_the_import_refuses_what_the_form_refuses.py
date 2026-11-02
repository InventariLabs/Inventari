"""Line import asks the questions the line form already asks.

The form's quantity field carries a ``min`` from its unit and
``DocumentLineCreate`` declares ``expected_quantity`` as ``Field(gt=0)``.
Import wrote straight to the table, so a pasted ``-5`` became a line the
screen showing it called invalid — and the totals every screen reads
("Plan", "received X of Y") are plain sums, so a receipt of 5 + 2 + (-5)
declared a plan of 2 and reported a complete receipt after two of seven
units.

These tests measure the door, the numbering the refusal uses and the
language it speaks, plus the gate that stops a document already carrying
such a line from being confirmed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document, DocumentLine

# A receipt takes only products on the list into stock: the flour the
# document starts with is one, named by its code.
_FLOUR_BARCODE = '5901234560026'


@pytest.fixture(autouse=True)
def _the_flour_is_on_the_list(h: ModuleTestHelper, doc_org: Organization) -> None:
    h.create_template(doc_org, name='Maka pszenna typ 550', barcode=_FLOUR_BARCODE)


def _create_doc(
    client: TestClient,
    headers: dict[str, str],
    partner_id: str,
    target_id: str,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        json={
            'type': 'IN',
            'partner_id': partner_id,
            'target_location_id': target_id,
            'lines': [
                {
                    'name': 'Maka pszenna typ 550',
                    'barcode': _FLOUR_BARCODE,
                    'expected_quantity': 5,
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return cast(dict[str, Any], resp.json())


@pytest.mark.integration
class TestImportRefusesWhatTheFormRefuses:
    def test_negative_quantity_is_a_row_error_and_reaches_no_line(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            str(doc_partner.id),
            str(doc_target_location.id),
        )
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json={
                'text': 'nazwa,ilosc\nMaka pszenna typ 550,2\nTrzeci wiersz,-5',
                'mapping_json': {'name': 'nazwa', 'quantity': 'ilosc'},
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['imported'] == 1
        assert body['failed'] == 1

        quantities = [
            line.quantity
            for line in db_session.query(DocumentLine)
            .filter(DocumentLine.document_id == doc['id'])
            .all()
        ]
        assert quantities, 'the document kept no lines at all'
        assert all(q > 0 for q in quantities), quantities

    def test_the_refused_row_is_numbered_as_the_preview_numbered_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """The mapping preview numbers data rows from 1; so does the refusal.

        The reader chooses the mapping against a preview that does not count
        the header. A refusal counting it pointed one row past the row it
        meant — at a row where, on the screen they had just seen, nothing was
        wrong.
        """
        doc = _create_doc(
            client,
            doc_auth_headers,
            str(doc_partner.id),
            str(doc_target_location.id),
        )
        text = 'nazwa,ilosc\nPierwszy,2\nDrugi,BANANA\nTrzeci,1'
        preview = client.post(
            '/api/v1/warehouse/import/parse-paste',
            json={'text': text},
            headers=doc_auth_headers,
        )
        assert preview.status_code == 200, preview.text
        rows = preview.json()['preview_rows']
        offending = next(
            i + 1 for i, row in enumerate(rows) if row['ilosc'] == 'BANANA'
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json={
                'text': text,
                'mapping_json': {'name': 'nazwa', 'quantity': 'ilosc'},
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        errors = resp.json()['errors']
        assert len(errors) == 1, errors
        assert errors[0]['row'] == offending

    def test_the_refusal_speaks_the_language_of_the_request(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            str(doc_partner.id),
            str(doc_target_location.id),
        )
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json={
                'text': 'nazwa,ilosc\nDrugi,BANANA',
                'mapping_json': {'name': 'nazwa', 'quantity': 'ilosc'},
            },
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
        )
        assert resp.status_code == 200, resp.text
        message = resp.json()['errors'][0]['error']
        assert 'nie jest liczbą' in message, message
        assert 'cannot read' not in message


@pytest.mark.integration
class TestConfirmationLooksAtTheLines:
    def _line_of(self, db_session: Session, doc_id: Any, quantity: str) -> None:
        doc = db_session.get(Document, doc_id)
        assert doc is not None
        db_session.add(
            DocumentLine(
                document_id=doc.id,
                name='Trzeci wiersz',
                quantity=Decimal(quantity),
                expected_quantity=Decimal(quantity),
                done_quantity=Decimal('0'),
                line_number=len(doc.lines) + 1,
            )
        )
        db_session.commit()

    def test_a_document_with_a_non_positive_line_is_not_confirmed(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """Lines written before this rule existed still meet it at the gate."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            str(doc_partner.id),
            str(doc_target_location.id),
        )
        self._line_of(db_session, doc['id'], '-5')

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == 400, resp.text

        fresh = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}', headers=doc_auth_headers
        ).json()
        assert fresh['status'] == 'DRAFT'

    def test_a_document_whose_lines_are_all_positive_still_confirms(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            str(doc_partner.id),
            str(doc_target_location.id),
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['status'] == 'CONFIRMED'


@pytest.mark.integration
class TestImportByCodeAlone:
    """A sheet with a code column and no name column still finds its products."""

    @pytest.mark.parametrize(
        ('header', 'mapping_field', 'code'),
        [('kod', 'barcode', _FLOUR_BARCODE), ('sku', 'sku', 'FLOUR-550')],
    )
    def test_a_code_column_names_the_line_after_the_product_it_finds(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        header: str,
        mapping_field: str,
        code: str,
    ) -> None:
        if mapping_field == 'sku':
            h.create_template(doc_org, name='Maka zytnia', sku=code)
        doc = _create_doc(
            client,
            doc_auth_headers,
            str(doc_partner.id),
            str(doc_target_location.id),
        )
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json={
                'text': f'{header},ilosc\n{code},3',
                'mapping_json': {mapping_field: header, 'quantity': 'ilosc'},
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body['imported'], body['matched'], body['failed']) == (1, 1, 0), body
        names = {
            line.name
            for line in db_session.query(DocumentLine)
            .filter(DocumentLine.document_id == doc['id'])
            .all()
        }
        assert names & {'Maka pszenna typ 550', 'Maka zytnia'}
        assert code not in names

    def test_a_row_with_neither_name_nor_code_is_still_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            str(doc_partner.id),
            str(doc_target_location.id),
        )
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json={
                'text': 'kod,ilosc\n,3',
                'mapping_json': {'barcode': 'kod', 'quantity': 'ilosc'},
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['failed'] == 1
