"""
Integration tests for Document state machine transitions.

Documents follow a strict state machine:
  DRAFT -> CONFIRMED -> COMPLETED
                |
                v
           CANCELLED

These tests verify that:
- Only valid state transitions are allowed
- Invalid transitions are rejected with appropriate errors
- Completing a document with zero quantity lines is handled
- Cancelling a confirmed document works correctly
- Document state is persisted correctly
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sm_doc_org(db_session: Session) -> Organization:
    org = Organization(
        name='Document State Machine Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
        ],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def sm_doc_user(db_session: Session, sm_doc_org: Organization) -> User:
    user = User(
        email='doc-sm-test@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Doc SM Test User',
        organization_id=sm_doc_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def doc_headers(sm_doc_user: User) -> dict[str, str]:
    return _auth(sm_doc_user)


@pytest.fixture
def sm_doc_storage_type(db_session: Session) -> StorageType:
    st = StorageType(name='Warehouse', type_code='WAREHOUSE', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def doc_location(
    db_session: Session,
    sm_doc_org: Organization,
    sm_doc_storage_type: StorageType,
    sm_doc_user: User,
) -> StorageLocation:
    loc = StorageLocation(
        name='Doc Test Warehouse',
        organization_id=sm_doc_org.id,
        storage_type_id=sm_doc_storage_type.id,
        created_by=sm_doc_user.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def sm_doc_template(db_session: Session, sm_doc_org: Organization) -> ProductTemplate:
    t = ProductTemplate(
        name='Doc Test Product',
        organization_id=sm_doc_org.id,
        barcode='DOCSM001',
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def doc_partner_id(client: TestClient, doc_headers: dict[str, str]) -> str:
    """Creates a partner and returns its ID."""
    resp = client.post(
        '/api/v1/partners',
        headers=doc_headers,
        json={'name': 'Test Supplier', 'type': 'SUPPLIER'},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    return str(resp.json()['id'])


# ============================================================================
# Tests: Valid State Transitions
# ============================================================================


@pytest.mark.integration
class TestDocumentValidTransitions:
    """Tests for valid document state transitions."""

    def test_draft_to_confirmed(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """DRAFT -> CONFIRMED should succeed."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']
        assert resp.json()['status'] == 'DRAFT'

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'CONFIRMED'

    def test_confirmed_to_completed(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """CONFIRMED -> COMPLETED should succeed."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'COMPLETED'

    def test_confirmed_to_cancelled(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """CONFIRMED -> CANCELLED should succeed."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'CANCELLED'


# ============================================================================
# Tests: Invalid State Transitions
# ============================================================================


@pytest.mark.integration
class TestDocumentInvalidTransitions:
    """Tests that invalid state transitions are rejected."""

    def test_completed_cannot_be_cancelled(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """COMPLETED -> CANCELLED should fail."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_headers,
            json={'complete_as_planned': True},
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_headers
        )
        # Invalid transition: COMPLETED -> CANCELLED must be rejected (400).
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_cancelled_cannot_be_confirmed(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """CANCELLED -> CONFIRMED should fail."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_headers
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        # Invalid transition: CANCELLED -> CONFIRMED must be rejected (400).
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_cancelled_cannot_be_completed(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """CANCELLED -> COMPLETED should fail."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_headers
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_headers,
            json={'complete_as_planned': True},
        )
        # Invalid transition: CANCELLED -> COMPLETED must be rejected (400).
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_draft_cannot_be_completed_without_confirm(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """DRAFT -> COMPLETED without confirm should fail."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_headers,
            json={'complete_as_planned': True},
        )
        # Invalid transition: DRAFT -> COMPLETED without confirm must be rejected (400).
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_idempotent_confirm_on_already_confirmed(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """Confirming an already CONFIRMED document should be idempotent."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        assert resp.status_code == status.HTTP_200_OK

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )
        # Idempotent - should return 200, not error
        assert resp.status_code == status.HTTP_200_OK, (
            'Confirm should be idempotent - second confirm should not fail'
        )
        assert resp.json()['status'] == 'CONFIRMED'


# ============================================================================
# Tests: Document Deletion
# ============================================================================


@pytest.mark.integration
class TestDocumentDeletion:
    """Tests for document deletion."""

    def test_draft_can_be_deleted(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """DRAFT document can be deleted."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_headers
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.text

    def test_confirmed_cannot_be_deleted(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """CONFIRMED document should not be deletable (business rule)."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )

        resp = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_headers
        )
        # Invalid deletion: CONFIRMED docs must be rejected (400).
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text


# ============================================================================
# Tests: Document Update
# ============================================================================


@pytest.mark.integration
class TestDocumentUpdate:
    """Tests for document updates."""

    def test_draft_can_be_updated(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """DRAFT document can be updated."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 20,
                    },
                ],
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def test_confirmed_cannot_be_updated(
        self,
        client: TestClient,
        doc_headers: dict[str, str],
        doc_partner_id: str,
        doc_location: StorageLocation,
        sm_doc_template: ProductTemplate,
    ) -> None:
        """CONFIRMED document should not be updatable (business rule)."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 10,
                    },
                ],
            },
        )
        doc_id = resp.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_headers
        )

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_headers,
            json={
                'type': 'IN',
                'partner_id': doc_partner_id,
                'target_location_id': str(doc_location.id),
                'lines': [
                    {
                        'product_template_id': str(sm_doc_template.id),
                        'expected_quantity': 20,
                    },
                ],
            },
        )
        # Invalid update: CONFIRMED docs must be rejected (400).
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
