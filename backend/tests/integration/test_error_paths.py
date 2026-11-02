"""Error-path tests for items CRUD and auth register endpoints.

Covers the 400 / 403 / 404 / 409 / 422 contract that the routers promise.
These tests are intentionally separate from the happy-path suites so that
a regression on any error branch shows up as one focused failure.
"""

from uuid import uuid4

import pytest
from fastapi import status


@pytest.mark.integration
class TestItemsCRUDErrors:
    """Items CRUD: 400 / 401 / 403 / 404 / 409 / 422 error branches."""

    def test_get_item_invalid_uuid_returns_422(self, client, auth_headers):
        response = client.get('/api/v1/items/not-a-uuid', headers=auth_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_get_item_not_found_returns_404(self, client, auth_headers):
        response = client.get(f'/api/v1/items/{uuid4()}', headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_item_unauthorized_returns_401(self, client, test_item):
        response = client.get(f'/api/v1/items/{test_item.id}')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_item_not_found_returns_404(self, client, auth_headers):
        response = client.put(
            f'/api/v1/items/{uuid4()}',
            headers=auth_headers,
            json={'name': 'Ghost'},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_item_invalid_payload_returns_422(
        self, client, auth_headers, test_item
    ):
        """Malformed UUID in storage_location_id fails Pydantic validation."""
        response = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'location_id': 'not-a-uuid'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_update_item_unauthorized_returns_401(self, client, test_item):
        response = client.put(
            f'/api/v1/items/{test_item.id}',
            json={'name': 'No auth'},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_item_not_found_returns_404(self, client, auth_headers):
        response = client.delete(f'/api/v1/items/{uuid4()}', headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_item_unauthorized_returns_401(self, client, test_item):
        response = client.delete(f'/api/v1/items/{test_item.id}')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_item_invalid_storage_returns_400_or_404(
        self, client, auth_headers, test_category
    ):
        """Unknown storage_id is rejected by the service layer."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'No storage',
                'location_id': str(uuid4()),
                'category_id': str(test_category.id),
                'quantity': 1,
            },
        )
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
        )

    def test_create_item_unauthorized_returns_401(self, client, test_storage_location):
        response = client.post(
            '/api/v1/items',
            json={
                'name': 'No auth',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_item_missing_required_field_returns_422(self, client, auth_headers):
        response = client.post(
            '/api/v1/items', headers=auth_headers, json={'quantity': 1}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestAuthRegisterErrors:
    """Auth register: 400 / 401 / 409 / 422 error branches."""

    def test_register_duplicate_email_returns_409(
        self, client, db_session, test_user, test_household
    ):
        """The 409 lives behind the invite gate now.

        Without a valid code the refusal has to be indistinguishable from the
        one an unknown address gets, so a duplicate only earns its own status
        once the caller has proved they were invited.
        """
        from datetime import UTC, datetime, timedelta

        from app.models.organization import OrganizationInvitation

        db_session.add(
            OrganizationInvitation(
                organization_id=test_household.id,
                code='DUPE2345',
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                created_by=test_user.id,
            )
        )
        db_session.commit()

        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': test_user.email,
                'password': 'Password123',
                'full_name': 'Duplicate',
                'invite_code': 'DUPE2345',
            },
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_register_invalid_email_returns_422(self, client):
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'not-an-email',
                'password': 'Password123',
                'full_name': 'Bad email',
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_missing_email_returns_422(self, client):
        response = client.post(
            '/api/v1/auth/register',
            json={'password': 'Password123', 'full_name': 'No email'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_missing_password_returns_422(self, client):
        response = client.post(
            '/api/v1/auth/register',
            json={'email': 'no.pwd@example.com', 'full_name': 'No pwd'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_weak_password_returns_422(self, client):
        """Single-char passwords violate the password complexity policy."""
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'weak.pwd@example.com',
                'password': 'x',
                'full_name': 'Weak pwd',
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_malformed_json_returns_422(self, client):
        response = client.post(
            '/api/v1/auth/register',
            content='{"email":',
            headers={'Content-Type': 'application/json'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
