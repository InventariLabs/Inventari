"""
Integration tests for the two internal document types, INTERNAL_IN and
INTERNAL_OUT (spelled ``PW`` and ``RW`` until the enum was made neutral).

Verifies:
- INTERNAL_IN creation (requires target_location_id, partner optional)
- INTERNAL_OUT creation (requires source_location_id, partner optional)
- INTERNAL_IN adds stock to target on completion
- INTERNAL_OUT removes stock from source on completion
- Validation errors for missing required locations
- Numbering is independent of IN/OUT
- Profile type_labels carry both
"""

from decimal import Decimal

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


@pytest.mark.integration
class TestInternalInDocumentType:
    """Tests for INTERNAL_IN (internal production receipt)."""

    def test_create_pw_document_success(
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
                'type': 'INTERNAL_IN',
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
        assert data['type'] == 'INTERNAL_IN'
        assert data['status'] == 'DRAFT'
        # A draft carries an identifier; its IR/ number arrives with
        # confirmation (see TestInternalInDocumentType numbering).
        assert data['number'].startswith('DRAFT-')
        assert data['partner_id'] is None

    def test_the_old_code_still_gets_in(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """``PW`` joins PZ/WZ/MM as a legacy code, so a caller written against
        the old vocabulary keeps working — it lands as INTERNAL_IN."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'PW',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['type'] == 'INTERNAL_IN'

        listed = client.get(
            '/api/v1/warehouse/documents?type=PW', headers=doc_auth_headers
        )
        assert listed.status_code == status.HTTP_200_OK
        assert [d['type'] for d in listed.json()['items']] == ['INTERNAL_IN']

    def test_create_pw_with_optional_partner(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """INTERNAL_IN can include a partner (e.g. responsible department/person)."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'INTERNAL_IN'
        assert data['partner_id'] == str(doc_partner.id)

    def test_pw_requires_target_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
    ) -> None:
        """INTERNAL_IN without target_location_id must fail validation."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_complete_pw_adds_stock_to_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_org: Organization,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Completing a INTERNAL_IN document adds stock to the target location."""
        # Create INTERNAL_IN document
        create_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'name': 'Produced Widget',
                        'expected_quantity': 20,
                    }
                ],
            },
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        doc_id = create_resp.json()['id']

        # Confirm
        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == status.HTTP_200_OK

        # Complete with done_quantity
        line_id = confirm_resp.json()['lines'][0]['id']
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'lines': [{'line_id': line_id, 'done_quantity': 20}]},
        )
        assert complete_resp.status_code == status.HTTP_200_OK

        # Verify an item was created at the target location
        item_count = (
            db_session.execute(
                text(
                    'SELECT COUNT(*) FROM items '
                    'WHERE organization_id = :org_id AND storage_location_id = :loc_id'
                ),
                {
                    'org_id': str(doc_org.id),
                    'loc_id': str(doc_target_location.id),
                },
            ).scalar()
            or 0
        )
        assert item_count >= 1

    def test_pw_numbering_independent_from_in(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """INTERNAL_IN and IN documents should have separate number sequences.

        Numbers are given out at confirmation, so the receipt is confirmed
        first: it takes IN/…/001, and the internal receipt — its own
        series — still starts at 001.
        """
        # Create one IN document
        in_resp = client.post(
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
        assert in_resp.status_code == status.HTTP_201_CREATED
        confirmed_in = client.patch(
            f'/api/v1/warehouse/documents/{in_resp.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed_in.status_code == status.HTTP_200_OK, confirmed_in.text
        assert confirmed_in.json()['number'].endswith('/001')

        # Now create INTERNAL_IN — should start at 001, not 002
        pw_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert pw_resp.status_code == status.HTTP_201_CREATED
        confirmed_pw = client.patch(
            f'/api/v1/warehouse/documents/{pw_resp.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed_pw.status_code == status.HTTP_200_OK, confirmed_pw.text
        pw_data = confirmed_pw.json()
        assert pw_data['number'].startswith('IR/')
        # its own counter, not a continuation of the IN one
        assert pw_data['number'].endswith('/001')


@pytest.mark.integration
class TestInternalOutDocumentType:
    """Tests for INTERNAL_OUT (internal consumption / issue)."""

    def test_create_rw_document_success(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'INTERNAL_OUT'
        assert data['status'] == 'DRAFT'
        # A draft carries an identifier; its II/ number arrives with
        # confirmation (see TestInternalOutDocumentType numbering).
        assert data['number'].startswith('DRAFT-')
        assert data['partner_id'] is None

    def test_create_rw_with_optional_partner(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        """INTERNAL_OUT can include a partner (e.g. requesting department)."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'INTERNAL_OUT'
        assert data['partner_id'] == str(doc_partner.id)

    def test_rw_requires_source_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
    ) -> None:
        """INTERNAL_OUT without source_location_id must fail validation."""
        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_complete_rw_removes_stock_from_source(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_org: Organization,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Completing an INTERNAL_OUT document removes stock from the source location."""
        from app.models.item import Item

        # Pre-seed an item at the source location
        item = Item(
            name='Bulk Material',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('50'),
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        # Create INTERNAL_OUT document
        create_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'item_id': str(item.id),
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        doc_id = create_resp.json()['id']

        # Confirm
        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == status.HTTP_200_OK

        # Complete
        line_id = confirm_resp.json()['lines'][0]['id']
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'lines': [{'line_id': line_id, 'done_quantity': 10}]},
        )
        assert complete_resp.status_code == status.HTTP_200_OK

        # Verify stock was reduced
        db_session.refresh(item)
        assert item.quantity == Decimal('40')

    def test_rw_numbering_independent_from_out(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        """INTERNAL_OUT and OUT documents should have separate number sequences.

        Numbers are given out at confirmation, so the dispatch is confirmed
        first: it takes OUT/…/001, and the internal issue — its own series —
        still starts at 001. The shelf carries stock of the record both
        lines name, so both reservations stand.
        """
        # Create one OUT document
        out_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 1}],
            },
        )
        assert out_resp.status_code == status.HTTP_201_CREATED
        confirmed_out = client.patch(
            f'/api/v1/warehouse/documents/{out_resp.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed_out.status_code == status.HTTP_200_OK, confirmed_out.text
        assert confirmed_out.json()['number'].endswith('/001')

        # Now create INTERNAL_OUT — should start at 001, not 002
        rw_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'source_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 1}],
            },
        )
        assert rw_resp.status_code == status.HTTP_201_CREATED
        confirmed_rw = client.patch(
            f'/api/v1/warehouse/documents/{rw_resp.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed_rw.status_code == status.HTTP_200_OK, confirmed_rw.text
        rw_data = confirmed_rw.json()
        assert rw_data['number'].startswith('II/')
        # its own counter, not a continuation of the OUT one
        assert rw_data['number'].endswith('/001')


@pytest.mark.integration
class TestInternalTypesListAndFilter:
    """Tests for listing and filtering the two internal types."""

    def test_list_documents_includes_pw_rw(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        """GET /warehouse returns INTERNAL_IN and INTERNAL_OUT documents."""
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'source_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 1}],
            },
        )

        list_resp = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        assert list_resp.status_code == status.HTTP_200_OK
        types = {d['type'] for d in list_resp.json()['items']}
        assert 'INTERNAL_IN' in types
        assert 'INTERNAL_OUT' in types

    def test_filter_by_pw_type(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Item,
    ) -> None:
        """GET /warehouse?type=INTERNAL_IN returns only INTERNAL_IN documents."""
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_OUT',
                'source_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 1}],
            },
        )

        filter_resp = client.get(
            '/api/v1/warehouse/documents?type=INTERNAL_IN', headers=doc_auth_headers
        )
        assert filter_resp.status_code == status.HTTP_200_OK
        docs = filter_resp.json()['items']
        assert len(docs) >= 1
        assert all(d['type'] == 'INTERNAL_IN' for d in docs)
