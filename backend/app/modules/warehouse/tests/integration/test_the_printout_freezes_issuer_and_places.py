"""A confirmed document prints the issuer and the places as they were.

The partner was already frozen at confirmation; the issuer block (name, tax
id, address) and the names of the locations were read at print time, so a
reprint after the company moved or a shelf was renamed showed the new values
on an old document. Documents confirmed before the snapshot existed carry
none and print from live data.
"""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document


def _text_of(pdf: bytes) -> str:
    reader = PdfReader(BytesIO(pdf))
    text = ' '.join((page.extract_text() or '') for page in reader.pages)
    return ' '.join(text.split())


def _confirmed_receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    location: StorageLocation,
    template: ProductTemplate,
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': 5}
            ],
        },
    )
    assert created.status_code == 201, created.text
    doc_id = str(created.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    return doc_id


@pytest.mark.integration
class TestPrintoutFreezesIssuerAndPlaces:
    def _change_the_world(
        self,
        db_session: Session,
        org: Organization,
        location: StorageLocation,
    ) -> None:
        org.name = 'Moved Company Ltd'
        org.address = {'street': 'New Street 99', 'city': 'Newtown'}
        location.name = 'Renamed Shelf'
        db_session.commit()

    def test_reprint_shows_the_values_of_the_day_of_confirmation(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_org.name = 'Original Company Ltd'
        doc_org.tax_id = 'PL1234567890'
        doc_org.address = {'street': 'Old Street 1', 'city': 'Oldtown'}
        doc_target_location.name = 'Original Shelf'
        db_session.commit()
        original_shelf = doc_target_location.name

        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        self._change_the_world(db_session, doc_org, doc_target_location)

        pdf = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf', headers=doc_auth_headers
        )
        assert pdf.status_code == 200
        text = _text_of(pdf.content)

        assert 'Original Company Ltd' in text
        assert 'Old Street 1' in text
        assert original_shelf in text
        assert 'Moved Company Ltd' not in text
        assert 'New Street 99' not in text
        assert 'Renamed Shelf' not in text

    def test_a_document_confirmed_before_the_snapshot_prints_live(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        document = db_session.get(Document, doc_id)
        assert document is not None
        assert document.print_snapshot is not None
        document.print_snapshot = None  # as if confirmed before the column
        self._change_the_world(db_session, doc_org, doc_target_location)

        pdf = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf', headers=doc_auth_headers
        )
        assert pdf.status_code == 200
        text = _text_of(pdf.content)

        assert 'Moved Company Ltd' in text
        assert 'New Street 99' in text
        assert 'Renamed Shelf' in text
