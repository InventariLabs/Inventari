"""
Integration tests for warehouse documents API endpoints.

Tests verify correctness of endpoints:
- POST /api/v1/warehouse/documents - create document
- GET /api/v1/warehouse/documents - list documents
- GET /api/v1/warehouse/documents/{id} - get document
- PUT /api/v1/warehouse/documents/{id} - update draft
- PATCH /api/v1/warehouse/documents/{id}/confirm - confirm document for execution
- PATCH /api/v1/warehouse/documents/{id}/complete - complete document
- PATCH /api/v1/warehouse/documents/{id}/cancel - cancel document
- DELETE /api/v1/warehouse/documents/{id} - delete draft
- UOM propagation through document lines and PDF content
"""

from decimal import Decimal
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import pypdf
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.approvals.models import ApprovalWorkflow
from app.modules.warehouse.tests.integration._records import sow as _sow


def _stand_on(db_session: Session, item: Item, location: StorageLocation) -> None:
    """Stand a record on a shelf for the document that follows.

    An outbound door takes stock off the shelf its document names, and the
    form's line search only ever offers what is standing there — so a test
    whose document draws from ``doc_source_location`` has to put its record
    on that shelf, not on the receiving one the shared fixture stands it on.
    """
    item.storage_location_id = location.id
    db_session.commit()


def _picked_line(record: Item, quantity: int) -> dict[str, Any]:
    """A line the form writes when a record is picked from the shelf: the
    record, its product card and the product's name."""
    return {
        'item_id': str(record.id),
        'product_template_id': str(record.template_id),
        'name': record.name,
        'expected_quantity': quantity,
    }


@pytest.mark.integration
class TestDocumentCreation:
    """Tests for document creation endpoint."""

    def test_create_in_draft_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'IN'
        assert data['status'] == 'DRAFT'
        # A draft carries an identifier of its own; the register's number
        # is drawn when the draft is confirmed.
        assert data['number'].startswith('DRAFT-')
        assert len(data['lines']) == 1
        assert data['lines'][0]['quantity'] == '10.000'
        assert data['lines'][0]['expected_quantity'] == '10.000'
        assert data['lines'][0]['done_quantity'] == '0.000'
        assert data['lines'][0]['line_status'] == 'PENDING'

        persisted_line = db_session.execute(
            text(
                'SELECT expected_quantity, done_quantity '
                'FROM document_lines WHERE document_id = :document_id'
            ),
            {'document_id': data['id']},
        ).one()
        assert persisted_line.expected_quantity == Decimal('10.000')
        assert persisted_line.done_quantity == Decimal('0.000')

    def test_create_document_uses_org_currency_over_preset(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
    ) -> None:
        """the document profile preset hardcoded EUR, ignoring the
        organization currency (USD here) — documents must follow the org."""
        preset = client.post(
            '/api/v1/warehouse/profile/apply-preset/Full Value',
            headers=doc_auth_headers,
        )
        assert preset.status_code == status.HTTP_200_OK

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['currency'] == doc_org.currency
        assert data['lines'][0]['currency'] == doc_org.currency

    def test_update_document_recomputes_header_currency_with_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
    ) -> None:
        """line edits re-resolve the currency — when the profile gains
        an explicit override after creation, the header must follow the lines
        instead of keeping the stale creation-time currency."""
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
                        'expected_quantity': 2,
                        'unit_price': '3.00',
                    }
                ],
            },
        )
        assert create.status_code == status.HTTP_201_CREATED, create.text
        doc_id = create.json()['id']
        assert create.json()['currency'] == doc_org.currency

        profile = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'default_currency': 'GBP'},
        )
        assert profile.status_code == status.HTTP_200_OK, profile.text

        update = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 4,
                        'unit_price': '3.00',
                    }
                ]
            },
        )
        assert update.status_code == status.HTTP_200_OK, update.text
        data = update.json()
        assert data['currency'] == 'GBP'
        assert data['lines'][0]['currency'] == 'GBP'

    def test_line_name_from_template_not_query(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """A template-linked line must snapshot the template name.

        Defense-in-depth: even if a stale search query leaks into ``name``
        (e.g. the user typed "Widg" before selecting the product), the persisted
        line name is the template's authoritative name — not free-text — so
        receipt/stock items don't fragment into phantom "Widg" rows.
        """
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'name': 'Widg',
                        'expected_quantity': 10,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        line = response.json()['lines'][0]
        assert line['name'] == doc_template.name
        assert line['name'] != 'Widg'

    def test_create_out_draft_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'OUT'
        assert data['status'] == 'DRAFT'

    def test_create_int_draft_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'INT'

    def test_create_document_empty_lines_422(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [],
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_create_document_invalid_type_422(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'XX',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_create_document_invalid_location_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(uuid4()),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_out_without_source_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """OUT documents require a source location."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'source location' in response.json()['detail']['message'].lower()

    def test_duplicate_creates_draft(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """POST /warehouse/documents/{id}/duplicate creates a new DRAFT
        with the same type/lines/quantities but a fresh number."""
        original = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'external_reference': 'REF-001',
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                        'unit': 'pcs',
                    }
                ],
            },
        )
        assert original.status_code == 201
        original_id = original.json()['id']
        original_number = original.json()['number']

        resp = client.post(
            f'/api/v1/warehouse/documents/{original_id}/duplicate',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 201
        dup = resp.json()
        assert dup['status'] == 'DRAFT'
        assert dup['id'] != original_id
        # Neither draft holds a number yet — each carries its own
        # identifier, and the copy stays a copy of the plan.
        assert dup['number'].startswith('DRAFT-')
        assert dup['number'] != original_number
        assert dup['type'] == 'IN'
        assert dup['external_reference'] == 'REF-001'
        assert len(dup['lines']) == 1
        assert dup['lines'][0]['expected_quantity'] == '10.000'
        assert dup['lines'][0]['done_quantity'] == '0.000'

        # Confirmed, the copy is a document of the register in its own
        # right, with a number the original does not carry.
        first = client.patch(
            f'/api/v1/warehouse/documents/{original_id}/confirm',
            headers=doc_auth_headers,
        )
        second = client.patch(
            f'/api/v1/warehouse/documents/{dup["id"]}/confirm', headers=doc_auth_headers
        )
        assert first.status_code == status.HTTP_200_OK, first.text
        assert second.status_code == status.HTTP_200_OK, second.text
        assert second.json()['number'].startswith('IN/')
        assert second.json()['number'] != first.json()['number']

    def test_a_duplicated_write_off_keeps_the_record_it_takes_from(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
    ) -> None:
        """A document that takes goods off a shelf names the record it takes,
        and confirming refuses a line that names none. The duplicate dropped
        that record on every line, so the copy of a scrap, an issue or a
        transfer could not be confirmed until each line was picked again."""
        original = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [_picked_line(doc_stock_item, 2)],
            },
        )
        assert original.status_code == 201, original.text

        dup = client.post(
            f'/api/v1/warehouse/documents/{original.json()["id"]}/duplicate',
            headers=doc_auth_headers,
        )
        assert dup.status_code == 201, dup.text
        assert dup.json()['lines'][0]['item_id'] == str(doc_stock_item.id)

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{dup.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm.status_code == 200, confirm.text

    def test_a_duplicate_leaves_out_a_record_since_deleted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
        db_session: Session,
    ) -> None:
        """A record deleted since the original was written is not offered to
        the copy: the duplicate is still made, and confirming it names the
        line that needs a record picked."""
        original = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [_picked_line(doc_stock_item, 2)],
            },
        )
        assert original.status_code == 201, original.text
        doc_stock_item.is_deleted = True
        db_session.commit()

        dup = client.post(
            f'/api/v1/warehouse/documents/{original.json()["id"]}/duplicate',
            headers=doc_auth_headers,
        )
        assert dup.status_code == 201, dup.text
        assert dup.json()['lines'][0]['item_id'] is None

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{dup.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm.status_code == 400, confirm.text
        assert 'line 1' in confirm.json()['detail']['message'].lower()

    def test_duplicate_nonexistent_returns_404(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f'/api/v1/warehouse/documents/{uuid4()}/duplicate',
            headers=doc_auth_headers,
        )
        # ValueError → ValidationException → 400 (consistent with other doc endpoints)
        assert resp.status_code in (400, 404)

    def test_duplicate_completed_document_creates_fresh_draft(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Duplicating a COMPLETED document produces a new DRAFT (not a copy
        of the terminal status). Useful for recurring receipts/issues."""
        original = client.post(
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
                        'unit': 'pcs',
                    }
                ],
            },
        )
        original_id = original.json()['id']
        # Confirm + complete the original
        client.post(
            f'/api/v1/warehouse/documents/{original_id}/confirm',
            headers=doc_auth_headers,
        )
        client.post(
            f'/api/v1/warehouse/documents/{original_id}/complete',
            headers=doc_auth_headers,
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{original_id}/duplicate',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 201
        dup = resp.json()
        assert dup['status'] == 'DRAFT'
        assert dup['id'] != original_id


@pytest.mark.integration
class TestDocumentWorkflow:
    """Tests for document status transitions and stock operations."""

    def test_confirm_in_marks_document_ready_without_stock_execution(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Confirming an IN document should only approve it for execution."""
        # Create draft
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 15,
                        'unit': 'pcs',
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        # Confirm
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['status'] == 'CONFIRMED'
        assert data['confirmed_at'] is not None
        assert data['lines'][0]['item_id'] is None
        assert data['lines'][0]['expected_quantity'] == '15.000'
        assert data['lines'][0]['done_quantity'] == '0.000'

        persisted_line = db_session.execute(
            text(
                'SELECT expected_quantity, done_quantity '
                'FROM document_lines WHERE document_id = :document_id'
            ),
            {'document_id': doc_id},
        ).one()
        assert persisted_line.expected_quantity == Decimal('15.000')
        assert persisted_line.done_quantity == Decimal('0.000')

    def test_complete_in_increases_existing_item_quantity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Completing an IN with an existing item should increase its quantity."""
        original_qty = float(doc_item.quantity)

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        db_session.refresh(doc_item)
        assert float(doc_item.quantity) == original_qty + 5

    def test_complete_out_decreases_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Completing an OUT should decrease item quantity."""
        _stand_on(db_session, doc_item, doc_source_location)
        original_qty = float(doc_item.quantity)

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_200_OK
        db_session.refresh(doc_item)
        assert float(doc_item.quantity) == original_qty - 3

    def test_complete_out_item_id_insufficient_stock_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """OUT completion should fail if item_id-based line requests more than item.quantity.

        Note: this exercises the dispatch-time check on ``Item.quantity``;
        the reservation-time hard fail for template-based lines is covered
        in ``test_confirm_out_insufficient_stock_400``.
        """
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 999,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'insufficient stock' in resp.json()['detail']['message'].lower()

    def test_confirm_out_insufficient_stock_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Confirm on template-based OUT must hard-fail when stock is short.

        Reservation in ``_reserve_quants_for_doc`` now raises ``ValueError`` on
        partial / failed reservation; router maps it to ``HTTP 400``. We never
        reach ``complete`` because confirm already rejected the document.
        """
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '5',
        )

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        doc_id = cast(UUID, resp.json()['id'])

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        detail = cast(dict[str, object], resp.json()['detail'])
        message = cast(str, detail['message']).lower()
        assert 'insufficient stock to confirm' in message
        # The screen counts in the same shape as every other quantity: the
        # database's own scale is not the reader's ("5.000 of 10.000").
        assert '5 of 10 could not be reserved' in message

    def test_confirm_out_full_stock_succeeds(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Happy path: confirm passes when the shelf fully covers the line."""
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK

    def test_complete_int_moves_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Completing an INT should move item to target location."""
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_200_OK
        db_session.refresh(doc_item)
        assert doc_item.storage_location_id == doc_target_location.id

    def test_confirm_already_confirmed_idempotent(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Confirming an already confirmed document is idempotent (200)."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'CONFIRMED'

    def test_complete_confirmed_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Completing a confirmed document should execute stock and close it."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'COMPLETED'
        assert resp.json()['completed_at'] is not None
        assert resp.json()['lines'][0]['item_id'] is not None
        assert resp.json()['lines'][0]['done_quantity'] == '1.000'
        assert resp.json()['lines'][0]['line_status'] == 'DONE'

        persisted_line = db_session.execute(
            text(
                'SELECT expected_quantity, done_quantity '
                'FROM document_lines WHERE document_id = :document_id'
            ),
            {'document_id': doc_id},
        ).one()
        assert persisted_line.expected_quantity == Decimal('1.000')
        assert persisted_line.done_quantity == Decimal('1.000')

    def test_complete_out_with_partial_done_quantity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Completing an OUT can execute less than the planned quantity."""
        _stand_on(db_session, doc_item, doc_source_location)
        original_qty = float(doc_item.quantity)

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']

        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == status.HTTP_200_OK

        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 2,
                        'discrepancy_code': 'SHORTAGE',
                        'discrepancy_reason': 'Supplier short shipped 3 pcs',
                    }
                ]
            },
        )

        assert complete_resp.status_code == status.HTTP_200_OK
        data = complete_resp.json()
        assert data['status'] == 'COMPLETED'
        assert data['lines'][0]['expected_quantity'] == '5.000'
        assert data['lines'][0]['done_quantity'] == '2.000'
        assert data['lines'][0]['line_status'] == 'EXCEPTION'
        assert data['lines'][0]['discrepancy_code'] == 'SHORTAGE'
        assert data['lines'][0]['discrepancy_reason'] == 'Supplier short shipped 3 pcs'

        db_session.refresh(doc_item)
        assert float(doc_item.quantity) == original_qty - 2

    def test_complete_partial_execution_persists_discrepancy_code_and_reason(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Partial execution should persist a structured discrepancy code and note."""
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']

        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == status.HTTP_200_OK

        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 2,
                        'discrepancy_code': 'SHORTAGE',
                        'discrepancy_reason': 'Supplier short shipped 3 pcs',
                    }
                ]
            },
        )

        assert complete_resp.status_code == status.HTTP_200_OK
        data = complete_resp.json()
        assert data['lines'][0]['done_quantity'] == '2.000'
        assert data['lines'][0]['discrepancy_code'] == 'SHORTAGE'
        assert data['lines'][0]['discrepancy_reason'] == 'Supplier short shipped 3 pcs'

        persisted_line = db_session.execute(
            text(
                'SELECT discrepancy_code, discrepancy_reason '
                'FROM document_lines WHERE document_id = :document_id'
            ),
            {'document_id': doc_id},
        ).one()
        assert persisted_line.discrepancy_code == 'SHORTAGE'
        assert persisted_line.discrepancy_reason == 'Supplier short shipped 3 pcs'

    def test_complete_partial_execution_requires_discrepancy_code(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Partial execution should require a structured discrepancy code."""
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']

        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == status.HTTP_200_OK

        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 2,
                    }
                ]
            },
        )

        assert complete_resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'discrepancy code' in complete_resp.json()['detail']['message'].lower()

    def test_complete_rejects_done_quantity_above_expected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Execution cannot exceed the planned quantity on a document line."""
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc = resp.json()
        doc_id = doc['id']
        line_id = doc['lines'][0]['id']

        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == status.HTTP_200_OK

        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 6,
                    }
                ]
            },
        )

        assert complete_resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'done quantity' in complete_resp.json()['detail']['message'].lower()

    def test_negative_done_quantity_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """A negative done_quantity is refused on a dispatch.

               Previously it passed validation with a discrepancy code, was persisted,
               and the executor skipped it → an EXCEPTION line carrying a negative
        quantity. Since the check moved from the schema to the line it
               applies to — corrections carry a signed delta, everything else cannot —
               so the refusal arrives as a 400 rather than a 422.
        """
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
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
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': -5,
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )

        assert complete_resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_over_done_quantity_400_includes_max(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Over-execution error message states the maximum allowed."""
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
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
            json={'lines': [{'line_id': line_id, 'done_quantity': 999}]},
        )

        assert complete_resp.status_code == status.HTTP_400_BAD_REQUEST
        message = complete_resp.json()['detail']['message'].lower()
        assert 'max' in message
        assert '10' in message

    def test_complete_draft_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Cannot complete a draft document — must confirm first."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cancel_draft_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Can cancel a draft document."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'CANCELLED'

    def test_cancel_confirmed_succeeds_and_releases_reservations(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Cancelling a CONFIRMED document returns 200 (releases reservations)."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'CANCELLED'


@pytest.mark.integration
class TestDocumentRoleGuards:
    """Cancel/delete document restricted to admin/manager."""

    def _create_draft(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> str:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        return str(resp.json()['id'])

    def test_cancel_user_403(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = self._create_draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        user = h.create_user(doc_org, email='cancel-user@example.com', role='user')
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=h.get_auth_headers(user),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_user_403(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = self._create_draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        user = h.create_user(doc_org, email='delete-user@example.com', role='user')
        resp = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=h.get_auth_headers(user),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cancel_manager_allowed(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = self._create_draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        manager = h.create_user(doc_org, email='cancel-mgr@example.com', role='manager')
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=h.get_auth_headers(manager),
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'CANCELLED'

    def _custom_role_user(
        self, h: Any, doc_org: Any, email: str, permissions: list[str]
    ) -> Any:
        """A plain member holding one org-scoped custom role."""
        from app.models.role import Role, UserRole

        user = h.create_user(doc_org, email=email, role='user')
        role = Role(
            organization_id=doc_org.id,
            name=f'Custom {email}',
            permissions=permissions,
            is_system=False,
        )
        h.db.add(role)
        h.db.flush()
        h.db.add(UserRole(user_id=user.id, role_id=role.id))
        h.db.commit()
        return user

    def test_cancel_custom_role_with_manage_allowed(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The cancel guard checks warehouse:manage, not the role name — a
        custom role holding it cancels like a manager."""
        doc_id = self._create_draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        # read+write pass the module router gate; manage is what the cancel
        # endpoint itself demands.
        user = self._custom_role_user(
            h,
            doc_org,
            'cancel-custom@example.com',
            ['warehouse:read', 'warehouse:write', 'warehouse:manage'],
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=h.get_auth_headers(user),
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'CANCELLED'

    def test_cancel_custom_role_without_manage_403(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """A custom role without warehouse:manage is refused like a plain
        member."""
        doc_id = self._create_draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        # read+write pass the module router gate, so the 403 must come from
        # the endpoint's own warehouse:manage guard.
        user = self._custom_role_user(
            h,
            doc_org,
            'cancel-noperm@example.com',
            ['warehouse:read', 'warehouse:write'],
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=h.get_auth_headers(user),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.integration
class TestDocumentList:
    """Tests for document listing and filtering."""

    def test_list_can_filter_by_discrepancy_code(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Document list can be filtered to a specific discrepancy code."""
        _stand_on(db_session, doc_item, doc_source_location)
        shortage_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'external_reference': 'DISC-SHORTAGE',
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        shortage_doc_id = shortage_resp.json()['id']
        shortage_line_id = shortage_resp.json()['lines'][0]['id']
        client.patch(
            f'/api/v1/warehouse/documents/{shortage_doc_id}/confirm',
            headers=doc_auth_headers,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{shortage_doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': shortage_line_id,
                        'done_quantity': 2,
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )

        damage_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'external_reference': 'DISC-DAMAGE',
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        damage_doc_id = damage_resp.json()['id']
        damage_line_id = damage_resp.json()['lines'][0]['id']
        client.patch(
            f'/api/v1/warehouse/documents/{damage_doc_id}/confirm',
            headers=doc_auth_headers,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{damage_doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': damage_line_id,
                        'done_quantity': 2,
                        'discrepancy_code': 'DAMAGE',
                    }
                ]
            },
        )

        resp = client.get(
            '/api/v1/warehouse/documents?discrepancy_code=SHORTAGE',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['total'] == 1
        assert data['items'][0]['external_reference'] == 'DISC-SHORTAGE'

    def test_list_search_matches_number_and_external_reference(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Can search documents by document number and external reference."""
        create_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'external_reference': 'PO-SEARCH-001',
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        created = create_resp.json()

        resp_by_reference = client.get(
            '/api/v1/warehouse/documents?search=PO-SEARCH-001',
            headers=doc_auth_headers,
        )

        assert resp_by_reference.status_code == status.HTTP_200_OK
        data_by_reference = resp_by_reference.json()
        assert data_by_reference['total'] >= 1
        assert any(doc['id'] == created['id'] for doc in data_by_reference['items'])

        resp_by_number = client.get(
            f'/api/v1/warehouse/documents?search={created["number"].split("/")[-1]}',
            headers=doc_auth_headers,
        )

        assert resp_by_number.status_code == status.HTTP_200_OK
        data_by_number = resp_by_number.json()
        assert any(doc['id'] == created['id'] for doc in data_by_number['items'])

    def test_list_filter_by_type(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_item: Item,
    ) -> None:
        """Can filter documents by type."""
        # Create IN
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        # Create OUT
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        resp = client.get(
            '/api/v1/warehouse/documents?type=IN',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['total'] >= 1
        for doc in data['items']:
            assert doc['type'] == 'IN'

    def test_list_filter_accepts_legacy_type_codes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """PZ/WZ/MM still address the types they were renamed from.

        The stored codes went canonical (IN/OUT/INT) but the filter compared
        raw strings, so a saved view or an integration filtering on ``PZ``
        answered "no documents" instead of "your receipts".
        """
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        resp = client.get(
            '/api/v1/warehouse/documents?type=pz', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['total'] >= 1
        for doc in data['items']:
            assert doc['type'] == 'IN'

    def test_list_filter_by_status(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Can filter documents by status."""
        # Create a draft
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        resp = client.get(
            '/api/v1/warehouse/documents?status=DRAFT',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        for doc in data['items']:
            assert doc['status'] == 'DRAFT'

    def test_list_filter_by_pending_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Can filter documents by status=PENDING_APPROVAL.

        The queue holds what is waiting for a decision, and only that. The
        workflow in place parks a confirmed document here; a document nobody
        has confirmed yet is not in the queue, whatever its value — the
        threshold's own boundary is covered where the threshold lives.
        """

        def _create_doc(
            lines: list[dict[str, object]],
        ) -> str:
            resp = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': lines,
                },
            )
            assert resp.status_code == status.HTTP_201_CREATED, resp.text
            return cast(str, resp.json()['id'])

        def _confirm(doc_id: str) -> None:
            resp = client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/confirm',
                headers=doc_auth_headers,
            )
            assert resp.status_code == status.HTTP_200_OK, resp.text

        # Confirmed under the workflow → PENDING_APPROVAL.
        waiting_doc_id = _create_doc(
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ]
        )
        _confirm(waiting_doc_id)

        # Never confirmed → not waiting on anybody.
        draft_doc_id = _create_doc(
            [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 1,
                    'unit_price': '10.00',
                }
            ]
        )

        resp = client.get(
            '/api/v1/warehouse/documents?status=PENDING_APPROVAL',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        ids = {d['id'] for d in data['items']}
        for doc in data['items']:
            assert doc['status'] == 'PENDING_APPROVAL'
        assert str(waiting_doc_id) in ids
        assert str(draft_doc_id) not in ids

    def test_list_filter_by_partner(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Can filter documents by partner_id."""
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        resp = client.get(
            f'/api/v1/warehouse/documents?partner_id={doc_partner.id}',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['total'] >= 1
        for doc in data['items']:
            assert doc['partner_id'] == str(doc_partner.id)

    def test_list_org_isolation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Documents from one org should not be visible to another org."""
        # Create a document in doc_org
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        # Create a different org + user
        from app.models.organization import Organization
        from app.services.auth_service import get_password_hash
        from app.services.token_service import create_access_token

        other_org = Organization(
            name='Other Org',
            enabled_modules=['core', 'items', 'locations', 'warehouse'],
        )
        db_session.add(other_org)
        db_session.commit()
        db_session.refresh(other_org)

        from app.models.user import User

        other_user = User(
            email='other@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='Other User',
            organization_id=other_org.id,
            role='admin',
            is_active=True,
        )
        db_session.add(other_user)
        db_session.commit()
        db_session.refresh(other_user)

        other_token = create_access_token(data={'sub': str(other_user.id)})
        other_headers = {'Authorization': f'Bearer {other_token}'}

        resp = client.get('/api/v1/warehouse/documents', headers=other_headers)

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['total'] == 0


@pytest.mark.integration
class TestDocumentHistory:
    """Tests that stock operations log source_document_id."""

    def test_complete_pz_logs_source_document_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """PZ completion should create ItemHistory with source_document_id."""
        resp = client.post(
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
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK

        from app.models.item_history import ItemHistory

        history = list(
            db_session.scalars(
                select(ItemHistory).where(ItemHistory.source_document_id == doc_id)
            ).all()
        )
        assert len(history) >= 1

    def test_complete_wz_logs_source_document_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """WZ completion should log source_document_id in history."""
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK

        from app.models.item_history import ItemHistory

        history = list(
            db_session.scalars(
                select(ItemHistory).where(ItemHistory.source_document_id == doc_id)
            ).all()
        )
        assert len(history) >= 1

    def test_complete_mm_logs_source_document_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """MM completion should log source_document_id in history."""
        _stand_on(db_session, doc_item, doc_source_location)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK

        from app.models.item_history import ItemHistory

        history = list(
            db_session.scalars(
                select(ItemHistory).where(ItemHistory.source_document_id == doc_id)
            ).all()
        )
        assert len(history) >= 1


@pytest.mark.integration
class TestDocumentNumbers:
    """Tests for automatic document numbering."""

    def test_auto_increment_within_year(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Document numbers should auto-increment: IN/YYYY/001, 002, ...

        The numbers are given out at confirmation: a draft is a plan, and
        three plans written and thrown away leave the register untouched.
        """
        numbers = []
        for _ in range(3):
            resp = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 1,
                        }
                    ],
                },
            )
            assert resp.status_code == status.HTTP_201_CREATED
            confirmed = client.patch(
                f'/api/v1/warehouse/documents/{resp.json()["id"]}/confirm',
                headers=doc_auth_headers,
            )
            assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
            numbers.append(confirmed.json()['number'])

        # Verify sequential
        assert all(n.startswith('IN/') for n in numbers), numbers
        seqs = [int(n.split('/')[-1]) for n in numbers]
        assert seqs == [seqs[0], seqs[0] + 1, seqs[0] + 2]

    def test_number_resets_per_type(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_item: Item,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Different document types have independent numbering.

        Numbers are given out at confirmation, so both documents are
        confirmed here — the dispatch takes stock off the shelf, which is
        sown first.
        """
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )
        resp_pz = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert resp_pz.status_code == status.HTTP_201_CREATED
        resp_wz = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert resp_wz.status_code == status.HTTP_201_CREATED

        confirmed_pz = client.patch(
            f'/api/v1/warehouse/documents/{resp_pz.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed_pz.status_code == status.HTTP_200_OK, confirmed_pz.text
        confirmed_wz = client.patch(
            f'/api/v1/warehouse/documents/{resp_wz.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed_wz.status_code == status.HTTP_200_OK, confirmed_wz.text

        pz_num = confirmed_pz.json()['number']
        wz_num = confirmed_wz.json()['number']

        assert pz_num.startswith('IN/')
        assert wz_num.startswith('OUT/')

    def test_numbering_with_dash_separator(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Numbering works correctly when format uses dashes instead of slashes."""
        client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'numbering_format': '{TYPE}-{YEAR}-{SEQ:03d}'},
        )

        numbers = []
        for _ in range(2):
            resp = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 1,
                            'unit': 'pcs',
                        }
                    ],
                },
            )
            assert resp.status_code == status.HTTP_201_CREATED
            confirmed = client.patch(
                f'/api/v1/warehouse/documents/{resp.json()["id"]}/confirm',
                headers=doc_auth_headers,
            )
            assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
            numbers.append(confirmed.json()['number'])

        assert numbers[0].startswith('IN-')
        assert numbers[0].endswith('001')
        assert numbers[1].endswith('002')


@pytest.mark.integration
class TestDocumentDelete:
    """Tests for document deletion."""

    def test_delete_draft_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT

        # Verify it's gone
        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_confirmed_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Cannot delete a confirmed document."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestDocumentUpdate:
    """Tests for updating draft documents."""

    def test_update_draft_notes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={'notes': 'Updated notes'},
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['notes'] == 'Updated notes'

    def test_update_confirmed_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Cannot update a confirmed document."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={'notes': 'Should fail'},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_draft_changes_partner(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
        doc_user: User,
    ) -> None:
        from app.models.partner import Partner

        new_partner = Partner(
            name='New Partner',
            type='SUPPLIER',
            organization_id=doc_partner.organization_id,
            created_by=doc_user.id,
        )
        db_session.add(new_partner)
        db_session.commit()
        db_session.refresh(new_partner)

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={'partner_id': str(new_partner.id)},
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['partner_id'] == str(new_partner.id)

    def test_update_draft_changes_notes_and_external_reference(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={
                'notes': 'Updated notes',
                'external_reference': 'PO-UPD-001',
            },
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['notes'] == 'Updated notes'
        assert data['external_reference'] == 'PO-UPD-001'

    def test_update_draft_replaces_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        resp = client.post(
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
        doc_id = resp.json()['id']
        assert len(resp.json()['lines']) == 1

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                    },
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    },
                ],
            },
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data['lines']) == 2
        assert data['lines'][0]['expected_quantity'] == '10.000'
        assert data['lines'][1]['expected_quantity'] == '3.000'


@pytest.mark.integration
class TestDocumentLineValidation:
    """Tests for document line validation after free-text line support was added."""

    def test_create_line_with_no_identifier_422(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        """Creating a line without item_id, product_template_id, or name should fail."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'quantity': 5,
                        'unit': 'pcs',
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_create_line_with_name_only_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
    ) -> None:
        """Name-only line (free-text) is allowed — useful for receipts of unknown products."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'name': 'New Product from Supplier',
                        'expected_quantity': 3,
                        'unit': 'pcs',
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['lines'][0]['name'] == 'New Product from Supplier'
        assert data['lines'][0]['item_id'] is None
        assert data['lines'][0]['product_template_id'] is None


@pytest.mark.integration
class TestDocumentValueLayer:
    """Tests for optional pricing/value fields on documents and lines."""

    def test_create_document_with_pricing_fields(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Document creation accepts optional unit_price and tax_rate on lines."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                        'unit': 'pcs',
                        'unit_price': 25.50,
                        'tax_rate': 23.00,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['unit_price'] == '25.50'
        assert data['lines'][0]['tax_rate'] == '23.00'

    def test_line_value_computation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """line_value = expected_quantity * unit_price, line_tax = line_value * tax_rate / 100."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 4,
                        'unit': 'pcs',
                        'unit_price': '100.00',
                        'tax_rate': '23.00',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['line_value'] == '400.00'
        assert data['lines'][0]['line_tax'] == '92.00'
        assert data['lines'][0]['line_gross'] == '492.00'

    def test_document_totals_computed_from_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Document totals (total_net, total_tax, total_gross) are summed from lines."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 2,
                        'unit': 'pcs',
                        'unit_price': '100.00',
                        'tax_rate': '23.00',
                    },
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                        'unit': 'pcs',
                        'unit_price': '50.00',
                        'tax_rate': '8.00',
                    },
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['total_net'] == '350.00'
        assert data['total_tax'] == '58.00'
        assert data['total_gross'] == '408.00'

    def test_document_without_pricing_has_null_values(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Document without pricing fields has null value fields."""
        response = client.post(
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
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['unit_price'] is None
        assert data['lines'][0]['tax_rate'] is None
        assert data['lines'][0]['line_value'] is None
        assert data['lines'][0]['line_tax'] is None
        assert data['lines'][0]['line_gross'] is None
        assert data['total_net'] is None
        assert data['total_tax'] is None
        assert data['total_gross'] is None

    def test_update_document_preserves_pricing_computation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Updating a draft document recomputes line and document values."""
        create_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                        'unit': 'pcs',
                        'unit_price': '10.00',
                        'tax_rate': '20.00',
                    }
                ],
            },
        )
        doc_id = create_resp.json()['id']

        update_resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'unit': 'pcs',
                        'unit_price': '20.00',
                        'tax_rate': '20.00',
                    }
                ]
            },
        )

        assert update_resp.status_code == status.HTTP_200_OK
        data = update_resp.json()
        assert data['lines'][0]['line_value'] == '100.00'
        assert data['lines'][0]['line_tax'] == '20.00'
        assert data['lines'][0]['line_gross'] == '120.00'


@pytest.mark.integration
class TestDocumentProfileAPI:
    """Tests for document profile management endpoints."""

    def test_get_profile_creates_default(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """GET /profile returns a profile, creating default if none exists."""
        response = client.get(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Simple'
        assert data['value_tracking_enabled'] is False
        assert data['tax_handling'] == 'NONE'
        assert data['numbering_format'] == '{TYPE}/{YEAR}/{SEQ:03d}'
        assert 'id' in data

    def test_update_profile_custom_values(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """PUT /profile updates profile fields."""
        response = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={
                'name': 'My Custom Profile',
                'value_tracking_enabled': True,
                'numbering_format': '{TYPE_LABEL}/{YEAR}/{SEQ:04d}',
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'My Custom Profile'
        assert data['value_tracking_enabled'] is True
        assert data['numbering_format'] == '{TYPE_LABEL}/{YEAR}/{SEQ:04d}'

    def test_update_profile_set_field_to_null(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """PUT /profile can explicitly set optional fields to null."""
        client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'type_labels': {'IN': 'PZ', 'OUT': 'WZ', 'INT': 'MM'}},
        )

        response = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'type_labels': None},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['type_labels'] is None

    def test_apply_preset_pl_magazyn(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """POST /profile/apply-preset/{preset} applies a named preset."""
        response = client.post(
            '/api/v1/warehouse/profile/apply-preset/PL Magazyn',
            headers=doc_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'PL Magazyn'
        assert data['value_tracking_enabled'] is True
        assert data['tax_handling'] == 'PER_LINE_RATE'
        # regional presets no longer pin a tax rate — a rate enters the
        # net/tax/gross arithmetic, so it belongs to the organization,
        # the same way the currency below does.
        assert data['default_tax_rate'] is None
        # the partner-tax-id requirement is law as well — the preset states
        # no opinion (None) and the organization's country answers.
        assert data['require_partner_tax_id'] is None
        # regional presets no longer pin a currency — the
        # organization currency is the source of truth.
        assert data['default_currency'] is None
        assert data['type_labels'] == {
            'IN': 'PZ',
            'OUT': 'WZ',
            'INT': 'MM',
            'INTERNAL_IN': 'PW',
            'INTERNAL_OUT': 'RW',
            'CORRECTION': 'KOR',
            'SCRAP': 'ZL',
        }

    def test_apply_preset_uk_warehouse_no_currency_override(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """the UK Warehouse preset used to pin GBP over the
        organization currency — it must leave the currency unset."""
        response = client.post(
            '/api/v1/warehouse/profile/apply-preset/UK Warehouse',
            headers=doc_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'UK Warehouse'
        assert data['default_currency'] is None
        assert data['type_labels'] == {
            'IN': 'GRN',
            'OUT': 'DN',
            'INT': 'ST',
            'INTERNAL_IN': 'IPR',
            'INTERNAL_OUT': 'IC',
            'CORRECTION': 'CORR',
        }

    def test_apply_preset_invalid_name_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """Applying an unknown preset returns 400."""
        response = client.post(
            '/api/v1/warehouse/profile/apply-preset/Non Existent Preset',
            headers=doc_auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_presets(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """GET /profile/presets returns available preset names."""
        response = client.get(
            '/api/v1/warehouse/profile/presets',
            headers=doc_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        presets = response.json()
        assert 'Simple' in presets
        assert 'PL Magazyn' in presets
        assert 'UK Warehouse' in presets
        assert 'DE Lager' in presets
        assert 'FR Entrepôt' in presets
        assert 'ES Almacén' in presets
        assert 'Full Value' in presets

    def test_profile_numbering_format_on_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Documents are numbered according to profile numbering_format."""
        client.post(
            '/api/v1/warehouse/profile/apply-preset/PL Magazyn',
            headers=doc_auth_headers,
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{response.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        number = confirmed.json()['number']
        assert number.startswith('PZ/')
        assert '/001' in number or '/0001' in number

    def test_profile_type_labels_on_document_number(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_item: Item,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Document numbers use type_labels from profile when set via TYPE_LABEL in format."""
        client.post(
            '/api/v1/warehouse/profile/apply-preset/PL Magazyn',
            headers=doc_auth_headers,
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                        'unit': 'pcs',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{response.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        number = confirmed.json()['number']
        assert number.startswith('WZ/')


@pytest.mark.integration
class TestDocumentProfilePadding:
    """number_padding is a first-class profile field controlling
    both warehouse documents and purchase orders."""

    def test_default_padding_is_in_range(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """GET /profile returns a default number_padding within 3..6.

        The seeded Simple preset encodes 3 digits; the column default is 4
        for new rows. Either is acceptable; both are within the validated
        range.
        """
        response = client.get(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['number_padding'] in {3, 4, 5, 6}

    def test_padding_round_trip(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """PUT /profile accepts and returns number_padding."""
        for value in (3, 4, 5, 6):
            response = client.put(
                '/api/v1/warehouse/profile',
                headers=doc_auth_headers,
                json={'number_padding': value},
            )
            assert response.status_code == status.HTTP_200_OK, (
                f'expected 200 for padding={value}, got {response.status_code}'
            )
            assert response.json()['number_padding'] == value

            get_resp = client.get(
                '/api/v1/warehouse/profile',
                headers=doc_auth_headers,
            )
            assert get_resp.status_code == status.HTTP_200_OK
            assert get_resp.json()['number_padding'] == value

    def test_padding_below_3_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """number_padding < 3 is rejected (422)."""
        response = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'number_padding': 2},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_padding_above_6_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """number_padding > 6 is rejected (422)."""
        response = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'number_padding': 7},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestDocumentPdfEndpoint:
    """Tests for GET /warehouse/documents/{doc_id}/pdf endpoint."""

    def _create_and_confirm_doc(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> str:
        """Helper: create + confirm a document, returns doc_id."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                        'unit': 'pcs',
                    }
                ],
            },
        )
        assert resp.status_code == 201
        doc_id = resp.json()['id']
        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()['status'] == 'CONFIRMED'
        return cast(str, doc_id)

    def test_download_pdf_confirmed_document_returns_pdf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = self._create_and_confirm_doc(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/pdf'
        # PDF magic bytes
        assert response.content[:4] == b'%PDF'

    def test_download_pdf_with_lang_pl_returns_pdf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = self._create_and_confirm_doc(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf?lang=pl',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/pdf'
        assert response.content[:4] == b'%PDF'

    def test_download_pdf_draft_document_is_refused_with_its_code(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        # Create document but do NOT confirm — stays in DRAFT status
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                        'unit': 'pcs',
                    }
                ],
            },
        )
        assert resp.status_code == 201
        doc_id = resp.json()['id']
        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf',
            headers=doc_auth_headers,
        )
        # The same refusal as the merged file's, and answered the same way: a
        # 400 whose code names it, not a 422 VALIDATION_ERROR a client could
        # not tell from a malformed request.
        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'DOCUMENT_PDF_REQUIRES_CONFIRMED'
        message = response.json()['detail']['message']
        assert 'confirmed or completed' in message
        assert 'DRAFT' in message

    def test_download_pdf_not_found_returns_404(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            f'/api/v1/warehouse/documents/{uuid4()}/pdf',
            headers=doc_auth_headers,
        )
        assert response.status_code == 404

    def test_download_pdf_content_disposition_header(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = self._create_and_confirm_doc(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        disposition = response.headers.get('content-disposition', '')
        assert 'attachment' in disposition
        assert '.pdf' in disposition


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


@pytest.mark.integration
class TestDocumentUomPropagation:
    def test_create_document_line_with_uom_id(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_uom_pcs: Uom,
    ) -> None:
        """Document line with explicit uom_id stores and returns it."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 25,
                        'uom_id': str(doc_uom_pcs.id),
                    }
                ],
            },
        )
        assert response.status_code == 201
        line = response.json()['lines'][0]
        assert line['uom_id'] == str(doc_uom_pcs.id)

    def test_document_line_without_uom_has_null(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Document line without uom_id has uom_id=null in response."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert response.status_code == 201
        line = response.json()['lines'][0]
        assert line['uom_id'] is None

    def test_document_line_inherits_uom_from_template(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template_with_uom: ProductTemplate,
        doc_uom_kg: Uom,
    ) -> None:
        """Document line auto-inherits uom_id from product template when not specified."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template_with_uom.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert response.status_code == 201
        line = response.json()['lines'][0]
        assert line['uom_id'] == str(doc_uom_kg.id)

    def test_explicit_uom_id_preserved_through_confirm(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_uom_pcs: Uom,
    ) -> None:
        """Document line uom_id survives confirm — still present after workflow."""
        doc = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                        'uom_id': str(doc_uom_pcs.id),
                    }
                ],
            },
        )
        doc_id = doc.json()['id']
        assert doc.json()['lines'][0]['uom_id'] == str(doc_uom_pcs.id)

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == 200
        assert confirmed.json()['lines'][0]['uom_id'] == str(doc_uom_pcs.id)


@pytest.mark.integration
class TestDocumentPdfContent:
    def test_pdf_contains_uom_symbol(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_uom_kg: Uom,
    ) -> None:
        """Confirmed document PDF includes the UOM symbol."""
        doc = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 50,
                        'uom_id': str(doc_uom_kg.id),
                    }
                ],
            },
        )
        doc_id = doc.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf?lang=pl',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        text = _extract_pdf_text(response.content)
        assert 'kg' in text, f"Expected 'kg' in document PDF but got:\n{text}"

    def test_pdf_contains_quantity_and_uom(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_uom_pcs: Uom,
    ) -> None:
        """PDF includes quantity and UOM from document lines."""
        doc = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 77,
                        'uom_id': str(doc_uom_pcs.id),
                    }
                ],
            },
        )
        doc_id = doc.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        text = _extract_pdf_text(response.content)
        assert '77' in text
        assert 'pcs' in text

    def test_pdf_wrong_uom_is_detected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_uom_kg: Uom,
    ) -> None:
        """PDF with kg must NOT contain pcs — test harness sanity check."""
        doc = client.post(
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
                        'uom_id': str(doc_uom_kg.id),
                    }
                ],
            },
        )
        doc_id = doc.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf',
            headers=doc_auth_headers,
        )
        assert response.status_code == 200
        text = _extract_pdf_text(response.content)
        assert 'kg' in text
        assert 'pcs' not in text


@pytest.mark.integration
class TestDocumentLineSerialNumber:
    """Tests for serial_number persistence on DocumentLine creation."""

    def test_serial_number_persisted_on_create(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                        'serial_number': 'SN-12345',
                        'batch_number': 'BATCH-2026-001',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['serial_number'] == 'SN-12345'
        assert data['lines'][0]['batch_number'] == 'BATCH-2026-001'

        persisted = db_session.execute(
            text(
                'SELECT serial_number, batch_number '
                'FROM document_lines WHERE document_id = :document_id'
            ),
            {'document_id': data['id']},
        ).one()
        assert persisted.serial_number == 'SN-12345'
        assert persisted.batch_number == 'BATCH-2026-001'

    def test_serial_number_optional(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        response = client.post(
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

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['serial_number'] is None


@pytest.mark.integration
class TestSimpleRateTaxFallback:
    """Tests for SIMPLE_RATE tax mode applying default_tax_rate to lines."""

    def _set_profile(
        self,
        db_session: Session,
        org_id: UUID,
        tax_handling: str,
        default_tax_rate: Decimal | None = None,
    ) -> None:
        import asyncio

        from app.modules.warehouse.document_profile_service import get_or_create_profile

        profile = asyncio.run(get_or_create_profile(db_session, org_id))
        profile.tax_handling = tax_handling
        profile.default_tax_rate = default_tax_rate
        db_session.commit()

    def test_simple_rate_applies_default_to_lines(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        self._set_profile(db_session, doc_org.id, 'SIMPLE_RATE', Decimal('23.00'))

        response = client.post(
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
                        'unit_price': '10.00',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['tax_rate'] == '23.00'

    def test_simple_rate_does_not_override_explicit_tax(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        self._set_profile(db_session, doc_org.id, 'SIMPLE_RATE', Decimal('23.00'))

        response = client.post(
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
                        'unit_price': '10.00',
                        'tax_rate': '8.00',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['tax_rate'] == '8.00'

    def test_per_line_rate_leaves_none(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        self._set_profile(db_session, doc_org.id, 'PER_LINE_RATE', Decimal('23.00'))

        response = client.post(
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
                        'unit_price': '10.00',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['tax_rate'] is None

    def test_simple_rate_without_rate_totals_gross_at_net(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        """The shape a preset without a rate now produces: SIMPLE_RATE and
        no default rate anywhere. The document is worth its net — gross
        falls back to net, it does not read as zero (a missing rate is "no
        tax is charged", not "the gross is unknown")."""
        self._set_profile(db_session, doc_org.id, 'SIMPLE_RATE', None)

        response = client.post(
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
                        'unit_price': '10.00',
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['lines'][0]['tax_rate'] is None
        assert data['total_net'] == '50.00'
        assert data['total_tax'] == '0.00'
        assert data['total_gross'] == '50.00'


class TestDoc12ValueTracking:
    """value tracking — required prices and price hints."""

    def _set_require_price(
        self, client: TestClient, headers: dict[str, str], value: bool
    ) -> None:
        response = client.put(
            '/api/v1/warehouse/profile',
            headers=headers,
            json={'require_unit_price': value},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['require_unit_price'] is value

    def test_create_blocks_missing_price_when_required(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        self._set_require_price(client, doc_auth_headers, True)
        try:
            blocked = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 10,
                        }
                    ],
                },
            )
            assert blocked.status_code == status.HTTP_400_BAD_REQUEST

            allowed = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'IN',
                    'partner_id': str(doc_partner.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 10,
                            'unit_price': '9.99',
                        }
                    ],
                },
            )
            assert allowed.status_code == status.HTTP_201_CREATED
        finally:
            self._set_require_price(client, doc_auth_headers, False)

    def test_create_transfer_without_price_when_required(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The screens offer a transfer no price field — a move between
        shelves changes where the goods stand, not what they are worth —
        so a rule asking every line for a price would leave the form with
        a refusal nobody reading it could answer."""
        self._set_require_price(client, doc_auth_headers, True)
        try:
            response = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': 'INT',
                    'source_location_id': str(doc_source_location.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': 3,
                        }
                    ],
                },
            )
            assert response.status_code == status.HTTP_201_CREATED, response.text
        finally:
            self._set_require_price(client, doc_auth_headers, False)

    def test_create_allowed_without_price_when_not_required(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_price_hint_returns_last_purchase(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        # Persist a completed receipt with a known price.
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 4,
                        'unit_price': '7.50',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        db_session.execute(
            text("UPDATE documents SET status = 'COMPLETED' WHERE id = :id"),
            {'id': doc_id},
        )
        db_session.commit()

        hint = client.get(
            '/api/v1/warehouse/price-hint',
            headers=doc_auth_headers,
            params={'template_id': str(doc_template.id)},
        )
        assert hint.status_code == status.HTTP_200_OK
        data = hint.json()
        assert Decimal(data['unit_price']) == Decimal('7.5')
        assert data['source'] == 'last_purchase'

    def test_price_hint_reports_a_failed_pricelist_lookup_as_a_500(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A defect in the pricelist lookup is a 500, not the next price.

        The lookup is asked only when the orders module is on for the
        organization (``order_side_async`` answers ``None`` otherwise), and a
        blanket ``except Exception`` around it fell through to the last
        purchase: a broken pricelist suggested a different price than the
        supplier's, with nothing to say the pricelist was never read.
        """
        from app.modules.warehouse import _documents_query_router

        class _BrokenOrders:
            async def list_pricelist_for_partner_async(
                self, *_args: object, **_kwargs: object
            ) -> list[object]:
                raise RuntimeError('simulated defect in the pricelist lookup')

        async def _orders_on(*_args: object) -> _BrokenOrders:
            return _BrokenOrders()

        monkeypatch.setattr(_documents_query_router, 'order_side_async', _orders_on)
        quiet_client = TestClient(client.app, raise_server_exceptions=False)

        hint = quiet_client.get(
            '/api/v1/warehouse/price-hint',
            headers=doc_auth_headers,
            params={
                'template_id': str(doc_template.id),
                'partner_id': str(doc_partner.id),
            },
        )

        assert hint.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, hint.text
        assert hint.json()['detail']['code'] == 'INTERNAL_ERROR'

    def test_price_hint_empty_when_no_history(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
    ) -> None:
        hint = client.get(
            '/api/v1/warehouse/price-hint',
            headers=doc_auth_headers,
            params={'template_id': str(doc_template.id)},
        )
        assert hint.status_code == status.HTTP_200_OK
        assert hint.json()['unit_price'] is None
        assert hint.json()['source'] is None

    def test_price_hint_reads_a_line_that_carries_only_its_record(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_stock_item: Item,
        db_session: Session,
    ) -> None:
        # The scanner builds a receipt line from the stock record alone: the
        # product it names is the one behind the record.
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'expected_quantity': 2,
                        'unit_price': '9.25',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        db_session.execute(
            text(
                'UPDATE document_lines SET product_template_id = NULL '
                'WHERE document_id = :id'
            ),
            {'id': created.json()['id']},
        )
        db_session.execute(
            text("UPDATE documents SET status = 'COMPLETED' WHERE id = :id"),
            {'id': created.json()['id']},
        )
        db_session.commit()

        hint = client.get(
            '/api/v1/warehouse/price-hint',
            headers=doc_auth_headers,
            params={'template_id': str(doc_stock_item.template_id)},
        )
        assert hint.status_code == status.HTTP_200_OK
        assert Decimal(hint.json()['unit_price']) == Decimal('9.25')
        assert hint.json()['source'] == 'last_purchase'
