"""Integration tests for equipment attachments and approval-status endpoints.

Covers the routes added to fix the asset-detail 404s:
- GET  /equipment/{item_id}/attachments
- POST /equipment/{item_id}/attachments
- DELETE /equipment/{item_id}/attachments/{attachment_id}
- GET  /equipment/{item_id}/approval-status
- POST /equipment/{item_id}/request-approval
"""

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.item import Item


@pytest.mark.integration
class TestEquipmentAttachments:
    """Tests for the /equipment/{item_id}/attachments routes."""

    def test_list_attachments_empty(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """GET returns an empty list when the asset has no attachments."""
        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_list_attachments_unknown_item_404(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """GET on a non-existent item returns 404."""
        response = client.get(
            '/api/v1/equipment/00000000-0000-0000-0000-000000000000/attachments',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_then_list_then_delete(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Full upload → list → delete cycle for an attachment."""
        # Upload
        upload = client.post(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers=eq_auth_headers,
            files={'file': ('invoice.pdf', b'%PDF-1.4 test', 'application/pdf')},
            data={'file_type': 'INVOICE'},
        )
        assert upload.status_code == status.HTTP_201_CREATED, upload.text
        att = upload.json()
        assert att['original_name'] == 'invoice.pdf'
        assert att['file_type'] == 'INVOICE'
        assert att['size_bytes'] > 0
        attachment_id = att['id']

        # List shows it
        listed = client.get(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers=eq_auth_headers,
        )
        assert listed.status_code == status.HTTP_200_OK
        assert len(listed.json()['items']) == 1
        assert listed.json()['items'][0]['id'] == attachment_id

        # Delete
        deleted = client.delete(
            f'/api/v1/equipment/{eq_item.id}/attachments/{attachment_id}',
            headers=eq_auth_headers,
        )
        assert deleted.status_code == status.HTTP_204_NO_CONTENT

        # List is empty again
        listed2 = client.get(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers=eq_auth_headers,
        )
        assert listed2.json()['items'] == []

    def test_upload_invalid_file_type_400(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Upload with an unsupported file_type category returns 400."""
        upload = client.post(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers=eq_auth_headers,
            files={'file': ('a.txt', b'hi', 'text/plain')},
            data={'file_type': 'NOT_A_CATEGORY'},
        )
        assert upload.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestEquipmentApprovalStatus:
    """Tests for the /equipment/{item_id}/approval-status routes."""

    def test_status_no_workflow(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """With no seeded workflow, has_workflow is False and request is null."""
        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/approval-status',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['has_workflow'] is False
        assert data['request_id'] is None
        assert data['status'] is None

    def test_status_unknown_item_404(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            '/api/v1/equipment/00000000-0000-0000-0000-000000000000/approval-status',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_request_approval_without_workflow_409(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Requesting approval when no workflow exists is a conflict."""
        response = client.post(
            f'/api/v1/equipment/{eq_item.id}/request-approval',
            headers=eq_auth_headers,
        )
        # approvals_api.request_approval raises ApprovalError when there is no
        # active workflow; the router translates that to a 409.
        assert response.status_code == status.HTTP_409_CONFLICT
