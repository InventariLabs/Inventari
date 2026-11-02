"""
Integration tests for CORRECTION document type.

Verifies:
- Correction creation against a completed IN document
- Correction fails when original is not COMPLETED
- Correction fails for invalid line numbers
- Completing a correction with positive delta adds stock
- Completing a correction with negative delta removes stock
- Corrections are listed via GET /{id}/corrections
- CORRECTION documents cannot be created via POST /warehouse (blocked)
- Correction document number is prefixed CORRECTION/
"""

import uuid
from io import BytesIO
from typing import Any

import pypdf
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _create_and_complete_in(
    client: TestClient,
    headers: dict[str, str],
    target_location_id: uuid.UUID,
    template_id: uuid.UUID,
    partner_id: uuid.UUID,
    quantity: int = 10,
    uom_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Helper: create, confirm, complete an IN document."""
    line: dict[str, Any] = {
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
        'done_quantity': quantity,
    }
    # The document form copies the unit off the product card, so a line the
    # application really creates names a unit. A line without one is a shape
    # only tests make.
    if uom_id is not None:
        line['uom_id'] = str(uom_id)
    create = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [line],
        },
    )
    assert create.status_code == 201, create.text
    doc_id = create.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert resp.status_code == 200, resp.text
    # The number is given out at confirmation: the create response was the
    # draft's identifier, and the caller names the document by its number.
    return {**create.json(), 'number': confirmed.json()['number']}


@pytest.mark.integration
class TestCorrectionDocumentCreation:
    """Tests for creating CORRECTION documents."""

    def test_create_correction_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """POST /warehouse/corrections creates a CORRECTION document."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': line_number,
                        'quantity_delta': -2,
                        'notes': 'Damaged items',
                    }
                ],
                'notes': 'Quality control',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'CORRECTION'
        assert data['status'] == 'DRAFT'
        # A draft carries an identifier; the COR/ number arrives when the
        # correction is confirmed.
        assert data['number'].startswith('DRAFT-')
        assert data['corrects_document_id'] == original['id']

    def test_the_read_names_the_corrected_document_type(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """A correction names the type of the document it corrects.

        A correction's lines are signed deltas, and the direction stock
        moves is the original's: the executor applies
        ``delta × correction_sign(original.type)``, so a negative
        correction of a dispatch-like original puts goods back on the
        shelf. Reading the delta's own sign named them "removed" while
        the shelf had just received them — the summary cannot tell the
        two cases apart without the original's type.
        """
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']
        create = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -2}],
            },
        )
        assert create.status_code == status.HTTP_201_CREATED, create.text
        correction_id = create.json()['id']

        read = client.get(
            f'/api/v1/warehouse/documents/{correction_id}', headers=doc_auth_headers
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        assert read.json()['corrects_document_type'] == 'IN'

        # A document that corrects nothing says so, in both directions:
        # the field is the correction's, not a guess about every document.
        plain = client.get(
            f'/api/v1/warehouse/documents/{original["id"]}', headers=doc_auth_headers
        )
        assert plain.json()['corrects_document_type'] is None

    def test_correction_of_a_line_that_names_a_unit_answers_201(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        doc_uom_kg: Any,
    ) -> None:
        """The correction endpoint answers with the document it just wrote.

        Every line the application creates names a unit, and the response
        serializes ``lines[].uom``. Lines built inside the writing session
        never fire the eager loader for it, so the serializer's reach used
        to become a lazy load on an async session — a 500 that arrived after
        the commit, reading "Failed to apply correction" over a correction
        that had in fact been saved.
        """
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            uom_id=doc_uom_kg.id,
        )
        line_number = original['lines'][0]['line_number']

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': line_number,
                        'quantity_delta': -2,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        data = response.json()
        assert data['type'] == 'CORRECTION'
        assert data['lines'][0]['uom']['id'] == str(doc_uom_kg.id)

    def test_an_adjustment_is_refused_a_correction_before_one_is_written(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_item: Any,
    ) -> None:
        """An adjustment's lines are already differences; a correction of one
        has no direction. The correction used to be saved anyway and failed
        only at completion — the refusal belongs where it is written."""
        adjustment = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'ADJUSTMENT',
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 2}],
            },
        )
        assert adjustment.status_code == 201, adjustment.text
        doc_id = adjustment.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == 200, done.text

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert (
            client.get(
                f'/api/v1/warehouse/documents/{doc_id}/corrections',
                headers=doc_auth_headers,
            ).json()['items']
            == []
        )

    def test_correction_requires_completed_original(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Cannot create correction for a DRAFT document."""
        create = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert create.status_code == 201, create.text
        doc_id = create.json()['id']

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
                'notes': 'Correcting a draft must still fail',
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_correction_invalid_line_number_returns_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Correction with non-existent line_number returns 400."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': 9999,
                        'quantity_delta': -1,
                    }
                ],
                'notes': 'Invalid line test',
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_correction_delta_below_negative_done_quantity_returns_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """the negative side is bounded by done_quantity — reversing
        more than was executed cannot be accepted."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': line_number,
                        'quantity_delta': -15,
                        'notes': 'Too much reversed',
                    }
                ],
                'notes': 'Should fail',
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize(
        'reason',
        [None, '', '   '],
        ids=['null', 'empty', 'whitespace-only'],
    )
    def test_correction_reason_required_rejects_blank(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        reason: str | None,
    ) -> None:
        """A correction rewrites recorded history and lands in the register,
        so it says why. The code carries that for every named
               reason; under OTHER the note is the reason, and a blank one is
               rejected server-side rather than trusted to the form."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']

        payload: dict[str, Any] = {
            'corrects_document_id': original['id'],
            'reason_code': 'OTHER',
            'lines': [{'original_line_number': line_number, 'quantity_delta': -1}],
        }
        if reason is not None:
            payload['notes'] = reason

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json=payload,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_correction_reason_code_is_recorded(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """The code lands on the document, so it can be counted later."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'WRONG_QUANTITY',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -1}],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['reason_code'] == 'WRONG_QUANTITY'

    def test_correction_rejects_a_reason_that_is_not_on_the_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'BECAUSE',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -1}],
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_correction_delta_equal_to_negative_done_quantity_accepted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """reversing exactly the executed quantity (result zero) is
        the legal boundary — the guard only rejects going below zero."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=5,
        )
        line_number = original['lines'][0]['line_number']

        response = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -5}],
                'notes': 'Full reversal',
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_correction_blocked_via_documents_endpoint(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """POST /warehouse with type=CORRECTION must be rejected."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'CORRECTION',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_list_corrections_for_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """GET /{id}/corrections returns corrections list."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']

        # No corrections yet
        response = client.get(
            f'/api/v1/warehouse/documents/{original["id"]}/corrections',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        assert response.json()['items'] == []

        # Create one correction
        client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -1}],
                'notes': 'Listing test correction',
            },
        )

        response = client.get(
            f'/api/v1/warehouse/documents/{original["id"]}/corrections',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        corrections = response.json()['items']
        assert len(corrections) == 1
        assert corrections[0]['type'] == 'CORRECTION'


@pytest.mark.integration
class TestCorrectionStockExecution:
    """Tests for stock quantity changes when a CORRECTION is completed."""

    def _get_item_quantity(
        self,
        db_session: Session,
        template_id: uuid.UUID,
        location_id: uuid.UUID,
    ) -> int:
        row = db_session.execute(
            text(
                'SELECT COALESCE(SUM(quantity), 0) FROM items '
                'WHERE template_id = :tid AND storage_location_id = :lid'
            ),
            {'tid': str(template_id), 'lid': str(location_id)},
        ).fetchone()
        return int(row[0]) if row else 0

    def _create_correction_and_complete(
        self,
        client: TestClient,
        headers: dict[str, str],
        original_id: str,
        line_number: int,
        qty_delta: int,
    ) -> None:
        create = client.post(
            '/api/v1/warehouse/corrections',
            headers=headers,
            json={
                'corrects_document_id': original_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': line_number,
                        'quantity_delta': qty_delta,
                    }
                ],
                'notes': 'Execution test correction',
            },
        )
        assert create.status_code == 201, create.text
        corr_id = create.json()['id']

        client.patch(f'/api/v1/warehouse/documents/{corr_id}/confirm', headers=headers)
        complete = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == 200, complete.text

    def test_complete_correction_negative_delta_removes_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        """Negative correction delta decreases target location stock."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=10,
        )
        qty_before = self._get_item_quantity(
            db_session, doc_template.id, doc_target_location.id
        )
        assert qty_before == 10

        line_number = original['lines'][0]['line_number']
        self._create_correction_and_complete(
            client,
            doc_auth_headers,
            original['id'],
            line_number,
            qty_delta=-3,
        )

        qty_after = self._get_item_quantity(
            db_session, doc_template.id, doc_target_location.id
        )
        assert qty_after == 7

    def _create_and_confirm_correction(
        self,
        client: TestClient,
        headers: dict[str, str],
        original_id: str,
        line_number: int,
        qty_delta: int,
    ) -> str:
        create = client.post(
            '/api/v1/warehouse/corrections',
            headers=headers,
            json={
                'corrects_document_id': original_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': line_number,
                        'quantity_delta': qty_delta,
                    }
                ],
                'notes': 'Explicit body correction',
            },
        )
        assert create.status_code == 201, create.text
        corr_id: str = create.json()['id']
        client.patch(f'/api/v1/warehouse/documents/{corr_id}/confirm', headers=headers)
        return corr_id

    def test_explicit_positive_body_on_a_decrease_is_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        """an API client must not flip a correction by completing it.

        ``done_quantity`` used to be constrained to ``>= 0``, so the only value
        a client could send for a -3 correction was +3 — and the executor took
        it at face value, adding stock where the document said remove.
        """
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=10,
        )
        line_number = original['lines'][0]['line_number']
        corr_id = self._create_and_confirm_correction(
            client, doc_auth_headers, original['id'], line_number, -3
        )
        line_id = client.get(
            f'/api/v1/warehouse/documents/{corr_id}', headers=doc_auth_headers
        ).json()['lines'][0]['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/complete',
            headers=doc_auth_headers,
            json={'lines': [{'line_id': line_id, 'done_quantity': 3}]},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert (
            self._get_item_quantity(db_session, doc_template.id, doc_target_location.id)
            == 10
        )

    def test_explicit_signed_body_on_a_decrease_removes_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        """The honest way to say it: a decrease is completed with a negative."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=10,
        )
        line_number = original['lines'][0]['line_number']
        corr_id = self._create_and_confirm_correction(
            client, doc_auth_headers, original['id'], line_number, -3
        )
        line_id = client.get(
            f'/api/v1/warehouse/documents/{corr_id}', headers=doc_auth_headers
        ).json()['lines'][0]['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/complete',
            headers=doc_auth_headers,
            json={'lines': [{'line_id': line_id, 'done_quantity': -2}]},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert (
            self._get_item_quantity(db_session, doc_template.id, doc_target_location.id)
            == 8
        )

    def test_complete_correction_positive_delta_adds_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        """Positive correction delta increases target location stock."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=10,
        )
        qty_before = self._get_item_quantity(
            db_session, doc_template.id, doc_target_location.id
        )
        assert qty_before == 10

        line_number = original['lines'][0]['line_number']
        self._create_correction_and_complete(
            client,
            doc_auth_headers,
            original['id'],
            line_number,
            qty_delta=5,
        )

        qty_after = self._get_item_quantity(
            db_session, doc_template.id, doc_target_location.id
        )
        assert qty_after == 15

    @pytest.mark.parametrize(('qty_delta', 'expected'), [(-1, 8), (2, 5)])
    def test_a_scrap_is_corrected_like_any_write_off(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
        qty_delta: int,
        expected: int,
    ) -> None:
        """A scrap takes goods off the shelf, so its correction moves the
        other way round: less scrapped puts goods back, more takes them off.

        The detail screen offered "New correction" on a completed scrap, the
        correction was saved, and completing it failed — the executor knew
        no direction for a scrap and gave up with a 500.
        """
        _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=10,
        )
        item_id = db_session.execute(
            text('SELECT id FROM items WHERE template_id = :tid'),
            {'tid': str(doc_template.id)},
        ).scalar_one()
        scrap = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [{'item_id': str(item_id), 'expected_quantity': 3}],
            },
        )
        assert scrap.status_code == 201, scrap.text
        scrap_id = scrap.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{scrap_id}/confirm', headers=doc_auth_headers
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{scrap_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == 200, done.text
        assert (
            self._get_item_quantity(db_session, doc_template.id, doc_target_location.id)
            == 7
        )

        self._create_correction_and_complete(
            client,
            doc_auth_headers,
            scrap_id,
            scrap.json()['lines'][0]['line_number'],
            qty_delta=qty_delta,
        )

        assert (
            self._get_item_quantity(db_session, doc_template.id, doc_target_location.id)
            == expected
        )

    def test_confirmed_correction_with_removed_item_fails_structured_and_stays_retryable(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        """completing a CONFIRMED correction whose item was removed
        from the catalog returns a structured CORRECTION_ITEM_MISSING error
        carrying the product name (translatable client-side), the document
        stays CONFIRMED so the retry path stays open, and the escape hatch
        (cancel of a CONFIRMED correction) works."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=10,
        )
        line_number = original['lines'][0]['line_number']
        create = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'notes': 'Audit remediation test',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -3}],
            },
        )
        assert create.status_code == 201, create.text
        corr_id = create.json()['id']

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == 200, confirm.text

        # Simulate the catalog item being permanently removed (soft-delete).
        db_session.execute(
            text('UPDATE items SET is_deleted = true WHERE template_id = :tid'),
            {'tid': str(doc_template.id)},
        )
        db_session.commit()

        complete = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == 400
        detail = complete.json()['detail']
        assert detail['code'] == 'CORRECTION_ITEM_MISSING'
        assert isinstance(detail.get('product'), str) and detail['product']
        assert str(doc_template.id) not in detail.get('message', '')

        # The document stays CONFIRMED — the retry path remains open and the
        # same structured error comes back instead of corrupting the doc.
        doc_resp = client.get(
            f'/api/v1/warehouse/documents/{corr_id}', headers=doc_auth_headers
        )
        assert doc_resp.status_code == 200
        assert doc_resp.json()['status'] == 'CONFIRMED'

        retry = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert retry.status_code == 400
        assert retry.json()['detail']['code'] == 'CORRECTION_ITEM_MISSING'

        # Escape hatch: a stuck CONFIRMED correction can be cancelled.
        cancel = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/cancel', headers=doc_auth_headers
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()['status'] == 'CANCELLED'


@pytest.mark.integration
class TestCorrectionDocumentUpdate:
    """CORRECTION documents in DRAFT must be structurally locked."""

    def test_update_correction_notes_allowed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Updating notes on a CORRECTION draft is permitted."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=5,
        )
        line_number = original['lines'][0]['line_number']
        corr_resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -1}],
                'notes': 'original reason',
            },
        )
        assert corr_resp.status_code == 201, corr_resp.text
        corr_id = corr_resp.json()['id']

        update_resp = client.put(
            f'/api/v1/warehouse/documents/{corr_id}',
            headers=doc_auth_headers,
            json={'notes': 'updated reason'},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()['notes'] == 'updated reason'

    def test_update_correction_lines_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Replacing lines on a CORRECTION draft must be blocked (400)."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=5,
        )
        line_number = original['lines'][0]['line_number']
        corr_resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -1}],
                'notes': 'Line-update block test',
            },
        )
        assert corr_resp.status_code == 201, corr_resp.text
        corr_id = corr_resp.json()['id']

        update_resp = client.put(
            f'/api/v1/warehouse/documents/{corr_id}',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 99,
                    }
                ]
            },
        )
        assert update_resp.status_code == 400
        assert (
            'Correction documents are locked' in update_resp.json()['detail']['message']
        )

    def test_update_correction_partner_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        """Changing partner on a CORRECTION draft must be blocked (400)."""
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=5,
        )
        line_number = original['lines'][0]['line_number']
        corr_resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -1}],
                'notes': 'Partner-update block test',
            },
        )
        assert corr_resp.status_code == 201, corr_resp.text
        corr_id = corr_resp.json()['id']

        update_resp = client.put(
            f'/api/v1/warehouse/documents/{corr_id}',
            headers=doc_auth_headers,
            json={'partner_id': str(doc_partner.id)},
        )
        assert update_resp.status_code == 400
        assert (
            'Correction documents are locked' in update_resp.json()['detail']['message']
        )


class TestCorrectionReasonTravels:
    """The form refuses to save without a reason, and the corrections list
    is where the parent document asks why - so the reason_code the create
    persisted has to come back on the summary rows."""

    def test_the_corrections_list_carries_the_reason_code(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        line_number = original['lines'][0]['line_number']

        created = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': line_number,
                        'quantity_delta': -1,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED

        listed = client.get(
            f'/api/v1/warehouse/documents/{original["id"]}/corrections',
            headers=doc_auth_headers,
        )
        assert listed.status_code == status.HTTP_200_OK
        rows = listed.json()['items']
        row = next(r for r in rows if r['id'] == created.json()['id'])
        assert row['reason_code'] == 'DATA_ENTRY_ERROR'


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


@pytest.mark.integration
class TestCorrectionPrintout:
    """The correction's printout names the document it corrects.

    Downloading it used to answer 500: the PDF renderer read the
    ``corrected_document`` relationship inside its worker thread, where a
    lazy load is a ``MissingGreenlet`` rather than a query — so the
    reference line the template prints for corrections never got to appear.
    """

    def test_pdf_points_at_the_corrected_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        original = _create_and_complete_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        created = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': original['lines'][0]['line_number'],
                        'quantity_delta': -1,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        correction_id = created.json()['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        pdf = client.get(
            f'/api/v1/warehouse/documents/{correction_id}/pdf?lang=pl',
            headers=doc_auth_headers,
        )
        assert pdf.status_code == status.HTTP_200_OK, pdf.text
        # pypdf may split a word across lines inside the PDF — compare
        # whitespace-normalized.
        flat = ' '.join(_pdf_text(pdf.content).split())
        assert 'Korekta dokumentu' in flat, flat
        assert original['number'] in flat, flat
