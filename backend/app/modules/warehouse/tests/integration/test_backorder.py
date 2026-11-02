"""Integration tests for automatic backorder generation on partial completion."""

from io import BytesIO

import pypdf
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation


@pytest.mark.integration
class TestBackorderCreation:
    """Tests for /08: backorder_id field and auto-generation logic."""

    def test_full_completion_no_backorder(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """When all lines are fully executed, no backorder is created."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        # No backorder should exist referencing this document
        list_resp = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        all_docs = list_resp.json()['items']
        backorders = [d for d in all_docs if d.get('backorder_id') == doc_id]
        assert len(backorders) == 0

    def test_partial_shortage_creates_backorder(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """SHORTAGE on lines creates a backorder with remaining quantities."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 10}],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 7,
                        'discrepancy_code': 'SHORTAGE',
                        'discrepancy_reason': 'Only 7 delivered',
                    }
                ]
            },
        )
        assert complete_resp.status_code == status.HTTP_200_OK

        # Find the backorder
        list_resp = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        all_docs = list_resp.json()['items']
        backorders = [d for d in all_docs if d.get('backorder_id') == doc_id]
        assert len(backorders) == 1

        # The list carries rows; the backorder's lines are on the document.
        bo = client.get(
            f'/api/v1/warehouse/documents/{backorders[0]["id"]}',
            headers=doc_auth_headers,
        ).json()
        assert bo['status'] == 'DRAFT'
        assert bo['type'] == 'IN'
        assert bo['partner_id'] == str(doc_partner.id)
        assert bo['target_location_id'] == str(doc_target_location.id)
        assert len(bo['lines']) == 1
        assert bo['lines'][0]['expected_quantity'] == '3.000'
        # The backorder links to its original through ``backorder_id``, which
        # the screens render in the reader's language. It used to store the
        # English sentence "Backorder for IN/…" in notes, which every
        # language showed verbatim and printed.
        assert bo['backorder_id'] == doc_id
        assert bo['notes'] is None

    def test_backorder_continues_the_receipts_own_number_series(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """The backorder is numbered by the same rule as the receipt it came from.

        A type with a numbering format of its own numbered the receipt by it
        and the backorder by the profile's unrelated format — the two pieces
        of one receipt's paper landed in two series, and the backorder's
        number could read lower than the receipt's.
        """
        client.put(
            '/api/v1/warehouse/settings/type-configs/IN',
            headers=doc_auth_headers,
            json={
                'document_type': 'IN',
                'sequence_format': 'PZ/{YEAR}/{SEQ:04d}',
            },
        )

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 10}],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        # The number is drawn at confirmation, from this type's own format.
        assert confirmed.json()['number'].startswith('PZ/')

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 7,
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )

        list_resp = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        backorders = [
            d for d in list_resp.json()['items'] if d.get('backorder_id') == doc_id
        ]
        assert len(backorders) == 1
        # The backorder is a draft too — its number arrives when it is
        # confirmed, by the same rule the receipt it came from was numbered.
        backorder_confirmed = client.patch(
            f'/api/v1/warehouse/documents/{backorders[0]["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert backorder_confirmed.status_code == status.HTTP_200_OK, (
            backorder_confirmed.text
        )
        assert backorder_confirmed.json()['number'].startswith('PZ/')

    def test_correction_no_backorder(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """CORRECTION documents never generate backorders."""
        # First create and complete a normal IN
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        # Create a correction
        correction_resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'quantity_delta': -2,
                    }
                ],
            },
        )
        if correction_resp.status_code == status.HTTP_201_CREATED:
            corr_id = correction_resp.json()['id']
            # Apply correction
            client.patch(
                f'/api/v1/warehouse/documents/{corr_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            )

            list_resp = client.get(
                '/api/v1/warehouse/documents', headers=doc_auth_headers
            )
            all_docs = list_resp.json()['items']
            backorders = [d for d in all_docs if d.get('backorder_id') == corr_id]
            assert len(backorders) == 0

    def test_rw_no_backorder(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """RW (internal consumption) never generates backorders."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'source_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 3}],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 1,
                        'discrepancy_code': 'SHORTAGE',
                        'discrepancy_reason': 'Only 1 consumed',
                    }
                ]
            },
        )

        list_resp = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        all_docs = list_resp.json()['items']
        backorders = [d for d in all_docs if d.get('backorder_id') == doc_id]
        assert len(backorders) == 0

    def test_backorder_preserves_partner_and_locations(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Backorder copies partner_id, source/target locations from original."""
        # The record stands on the shelf this document draws from: an
        # outbound door takes stock off the shelf it names, and the line
        # search only ever offers what is standing there.
        doc_item.storage_location_id = doc_source_location.id
        db_session.commit()
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 8}],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 5,
                        'discrepancy_code': 'SHORTAGE',
                        'discrepancy_reason': 'Only 5 available',
                    }
                ]
            },
        )

        list_resp = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        all_docs = list_resp.json()['items']
        backorders = [d for d in all_docs if d.get('backorder_id') == doc_id]
        assert len(backorders) == 1

        bo = backorders[0]
        assert bo['partner_id'] == str(doc_partner.id)
        assert bo['source_location_id'] == str(doc_source_location.id)
        assert bo['target_location_id'] == str(doc_target_location.id)

    def test_new_document_has_no_backorder_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """Newly created documents have backorder_id = None."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data.get('backorder_id') is None

    def test_backorder_id_in_get_response(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """GET /warehouse/documents/{id} returns backorder_id field."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        doc_id = resp.json()['id']

        get_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
        )
        assert get_resp.status_code == status.HTTP_200_OK
        assert 'backorder_id' in get_resp.json()

    def test_complete_response_includes_generated_backorder(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """Complete response points at the auto-created backorder."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 10}],
            },
        )
        doc_id = resp.json()['id']
        line_id = resp.json()['lines'][0]['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 7,
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )
        assert complete_resp.status_code == status.HTTP_200_OK
        payload = complete_resp.json()
        backorder_id = payload.get('generated_backorder_id')
        assert backorder_id is not None
        assert payload.get('generated_backorder_number')

        # The id points at the actual backorder document.
        bo_resp = client.get(
            f'/api/v1/warehouse/documents/{backorder_id}',
            headers=doc_auth_headers,
        )
        assert bo_resp.status_code == status.HTTP_200_OK
        assert bo_resp.json()['backorder_id'] == doc_id

    def test_complete_response_without_backorder_has_null_field(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """Full completion yields no generated backorder reference."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        doc_id = resp.json()['id']
        line_id = resp.json()['lines'][0]['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'lines': [{'line_id': line_id, 'done_quantity': 5}]},
        )
        assert complete_resp.status_code == status.HTTP_200_OK
        assert complete_resp.json().get('generated_backorder_id') is None

    def test_get_original_document_lists_generated_backorder(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """GET on the original doc exposes its child backorder."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 10}],
            },
        )
        doc_id = resp.json()['id']
        line_id = resp.json()['lines'][0]['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 4,
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )

        get_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
        )
        assert get_resp.status_code == status.HTTP_200_OK
        payload = get_resp.json()
        assert payload.get('generated_backorder_id') is not None
        assert payload.get('generated_backorder_number')


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


@pytest.mark.integration
class TestThePrintoutNamesTheDocumentItContinues:
    """The paper a backorder prints points at the receipt it continues.

    The stored English sentence the backorder used to carry in its notes
    ("Backorder for IN/…") is dropped, and no screen-facing column links the
    two documents — so the printout renders the reference line, in the
    document's language, the way a correction prints the document it
    corrects.
    """

    def test_printout_points_at_the_receipt(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 10}],
            },
        )
        doc = resp.json()
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        receipt_number = confirmed.json()['number']
        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': doc['lines'][0]['id'],
                        'done_quantity': 7,
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

        listed = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        backorder = next(
            d for d in listed.json()['items'] if d.get('backorder_id') == doc['id']
        )
        client.patch(
            f'/api/v1/warehouse/documents/{backorder["id"]}/confirm',
            headers=doc_auth_headers,
        )

        pdf = client.get(
            f'/api/v1/warehouse/documents/{backorder["id"]}/pdf?lang=pl',
            headers=doc_auth_headers,
        )
        assert pdf.status_code == status.HTTP_200_OK, pdf.text
        # pypdf may split a word across lines inside the PDF — compare
        # whitespace-normalized.
        flat = ' '.join(_pdf_text(pdf.content).split())
        assert 'Dostawa uzupełniająca do' in flat, flat
        assert receipt_number in flat, flat
