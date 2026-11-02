"""Selected documents print as one PDF, in the order they were chosen.

Forty dispatches a day used to be forty downloads, each opened and sent to
the printer by hand. The register now asks for the selection and gets back a
single file; a document that cannot be printed refuses the whole file by name
rather than leaving a gap in the stack.
"""

from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    location: StorageLocation,
    template: ProductTemplate,
    *,
    confirm: bool,
) -> dict[str, Any]:
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
    doc: dict[str, Any] = created.json()
    if confirm:
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=headers
        )
        assert confirmed.status_code == 200, confirmed.text
        doc = confirmed.json()
    return doc


def _page_texts(pdf: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf))
    return [' '.join((page.extract_text() or '').split()) for page in reader.pages]


@pytest.mark.integration
class TestSelectedDocumentsPrintAsOneFile:
    def test_three_documents_come_back_as_one_pdf_in_the_order_given(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        docs = [
            _create_document(
                client,
                doc_auth_headers,
                doc_partner,
                doc_target_location,
                doc_template,
                confirm=True,
            )
            for _ in range(3)
        ]
        wanted = [docs[2], docs[0], docs[1]]

        resp = client.get(
            '/api/v1/warehouse/documents/pdf',
            headers=doc_auth_headers,
            params={'ids': [d['id'] for d in wanted]},
        )

        assert resp.status_code == 200, resp.text
        assert resp.headers['content-type'] == 'application/pdf'
        pages = _page_texts(resp.content)
        assert len(pages) == 3
        for page, doc in zip(pages, wanted, strict=True):
            assert doc['number'] in page

    def test_a_draft_refuses_the_whole_file_and_is_named(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        confirmed = _create_document(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            confirm=True,
        )
        draft = _create_document(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            confirm=False,
        )

        resp = client.get(
            '/api/v1/warehouse/documents/pdf',
            headers=doc_auth_headers,
            params={'ids': [confirmed['id'], draft['id']]},
        )

        assert resp.status_code == 400
        assert resp.json()['detail']['code'] == 'DOCUMENTS_PDF_REQUIRE_CONFIRMED'
        message = resp.json()['detail']['message']
        assert draft['number'] in message
        assert confirmed['number'] not in message

    def test_an_unknown_document_is_not_found(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents/pdf',
            headers=doc_auth_headers,
            params={'ids': [str(uuid4())]},
        )
        assert resp.status_code == 404

    def test_an_empty_selection_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get('/api/v1/warehouse/documents/pdf', headers=doc_auth_headers)
        assert resp.status_code == 422
