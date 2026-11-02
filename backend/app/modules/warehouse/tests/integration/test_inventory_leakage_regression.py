"""
Integration tests for Theme 2 CRIT inventory leakage fixes.

Each test verifies a specific CRIT finding via the API.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation


@pytest.mark.integration
class TestAdjustmentDocument:
    """CRIT #1: ADJUSTMENT document type moves stock correctly."""

    def test_adjustment_positive_increases_quantity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        """ADJUSTMENT +5 should increase item.quantity."""
        initial_qty = test_item.quantity or Decimal('0')

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=auth_headers,
            json={
                'type': 'ADJUSTMENT',
                'target_location_id': str(test_storage_location.id),
                'lines': [
                    {
                        'item_id': str(test_item.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert response.status_code == 201
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=auth_headers
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp.status_code == 200

        db_session.refresh(test_item)
        assert test_item.quantity == initial_qty + 5


@pytest.mark.integration
class TestScrapQuantLeak:
    """CRIT #2: SCRAP decrements the stock even without source_location_id."""

    def test_scrap_decrements_item_quantity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        """SCRAP should decrement item.quantity."""
        initial_qty = test_item.quantity or Decimal('0')

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'item_id': str(test_item.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert response.status_code == 201
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=auth_headers
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp.status_code == 200

        db_session.refresh(test_item)
        assert test_item.quantity == initial_qty - 1


def _add_document_workflow(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Put an active document workflow in place mid-test."""
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=auth_headers,
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'is_active': True,
            'expected_scope': {'holds': 'all'},
            'name': 'Workflow arrived late',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
class TestDuplicateApprovalBlock:
    """Approvals: duplicate pending request returns 409."""

    def test_duplicate_approval_request_returns_409(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Second approval request on same doc should return 409.

        The document is confirmed before the workflow exists, because a
        workflow in place gates the confirmation itself and raises the
        request then — leaving the manual door open here is what makes a
        second request possible at all.
        """
        doc_resp = client.post(
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
                        'unit_price': '50.00',
                    }
                ],
            },
        )
        doc_id = doc_resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        _add_document_workflow(client, doc_auth_headers)

        resp1 = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=doc_auth_headers,
        )
        assert resp1.status_code in (200, 201)

        resp2 = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=doc_auth_headers,
        )
        assert resp2.status_code == 409


@pytest.mark.integration
class TestStorageDeleteGuard:
    """CRIT #17: Deleting storage with items returns error."""

    def test_delete_storage_with_items_returns_error(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        """Deleting storage with items should fail."""
        response = client.delete(
            f'/api/v1/locations/{test_storage_location.id}',
            headers=auth_headers,
        )
        assert response.status_code in (400, 409)
