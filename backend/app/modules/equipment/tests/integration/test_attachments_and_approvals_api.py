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

    def test_a_refused_type_is_answered_as_an_item_attachment_is(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """415 FILE_TYPE_NOT_ALLOWED in the reader's language, naming the
        kinds of file an asset takes rather than the type it was sent as."""
        upload = client.post(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers={**eq_auth_headers, 'Accept-Language': 'pl'},
            files={'file': ('manual.doc', b'old word file', 'application/msword')},
            data={'file_type': 'MANUAL'},
        )

        assert upload.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        detail = upload.json()['detail']
        assert detail['code'] == 'FILE_TYPE_NOT_ALLOWED'
        assert detail['message'] == (
            'Niedozwolony typ pliku. Dozwolone: '
            'docx, gif, jpg, pdf, png, txt, webp, xls, xlsx, zip'
        )

    def test_bytes_that_contradict_their_type_are_answered_as_an_item_attachment_is(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        upload = client.post(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers={**eq_auth_headers, 'Accept-Language': 'pl'},
            files={'file': ('scan.pdf', b'not a pdf at all', 'application/pdf')},
            data={'file_type': 'INVOICE'},
        )

        assert upload.status_code == status.HTTP_400_BAD_REQUEST
        detail = upload.json()['detail']
        assert detail['code'] == 'FILE_SIGNATURE_MISMATCH'
        assert detail['message'] == (
            'Sygnatura pliku nie zgadza się z zadeklarowanym typem'
        )

    def test_a_file_over_the_limit_names_the_limit(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """413 FILE_TOO_LARGE with the asset's own limit, not an item's."""
        from app.core.upload_validation import UploadPolicy
        from app.modules.equipment import attachment_service

        monkeypatch.setattr(
            attachment_service,
            'ATTACHMENT_POLICY',
            UploadPolicy(
                max_bytes=1024,
                content_types=attachment_service.ATTACHMENT_POLICY.content_types,
            ),
        )
        upload = client.post(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers={**eq_auth_headers, 'Accept-Language': 'pl'},
            files={'file': ('scan.pdf', b'%PDF-1.4 ' + b'x' * 2048, 'application/pdf')},
            data={'file_type': 'INVOICE'},
        )

        assert upload.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        detail = upload.json()['detail']
        assert detail['code'] == 'FILE_TOO_LARGE'
        assert detail['message'] == 'Plik przekracza dozwolony rozmiar (1 KB)'


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
