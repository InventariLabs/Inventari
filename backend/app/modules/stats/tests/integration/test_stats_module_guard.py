"""
Lock-before-change tests for stats API module guard.

stats is currently in TRUSTED_CORE_MODULES, which means require_module('stats')
always returns True regardless of organization enabled_modules. These tests
document that current behavior. If stats is removed from TRUSTED_CORE_MODULES,
these tests should be updated to assert 403 when disabled.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash


@pytest.mark.integration
class TestStatsModuleGuard:
    """Lock the stats module guard behavior."""

    def test_stats_overview_returns_200_when_module_enabled(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get('/api/v1/stats/overview', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK

    def test_stats_overview_returns_200_even_when_not_in_enabled_modules(
        self, client: TestClient, db_session: Session
    ) -> None:
        """stats is in TRUSTED_CORE_MODULES, so it bypasses enabled_modules check."""
        org = Organization(
            name='No Stats Org',
            enabled_modules=['core', 'items', 'locations', 'categories'],
        )
        db_session.add(org)
        db_session.flush()

        user = User(
            email='nostats@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='No Stats User',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        token_data: dict[str, str] = {'sub': str(user.id)}
        token = create_access_token(data=token_data)
        headers: dict[str, str] = {'Authorization': f'Bearer {token}'}

        response = client.get('/api/v1/stats/overview', headers=headers)

        assert response.status_code == status.HTTP_200_OK

    def test_stats_overview_returns_401_without_auth(self, client: TestClient) -> None:
        response = client.get('/api/v1/stats/overview')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_stats_by_storage_returns_200_even_when_not_in_enabled_modules(
        self, client: TestClient, db_session: Session
    ) -> None:
        """stats is in TRUSTED_CORE_MODULES, so it bypasses enabled_modules check."""
        org = Organization(
            name='No Stats Org 2',
            enabled_modules=['core', 'items', 'locations', 'categories'],
        )
        db_session.add(org)
        db_session.flush()

        user = User(
            email='nostats2@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='No Stats User 2',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        token_data: dict[str, str] = {'sub': str(user.id)}
        token = create_access_token(data=token_data)
        headers: dict[str, str] = {'Authorization': f'Bearer {token}'}

        response = client.get('/api/v1/stats/by-location', headers=headers)

        assert response.status_code == status.HTTP_200_OK

    def test_organization_with_null_modules_has_stats_enabled_by_default(
        self, client: TestClient, db_session: Session
    ) -> None:
        org = Organization(
            name='Null Modules Org',
            enabled_modules=None,
        )
        db_session.add(org)
        db_session.flush()

        user = User(
            email='nullmodules@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='Null Modules User',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        token_data: dict[str, str] = {'sub': str(user.id)}
        token = create_access_token(data=token_data)
        headers: dict[str, str] = {'Authorization': f'Bearer {token}'}

        response = client.get('/api/v1/stats/overview', headers=headers)

        assert response.status_code == status.HTTP_200_OK
