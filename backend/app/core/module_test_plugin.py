"""Pytest plugin providing auto-fixtures for ``@pytest.mark.module('name')`` tests.

When a test function (or its class/module) carries the ``module`` marker,
four fixtures become available with zero boilerplate:

- ``module_org``          — Organization with the marked module enabled
- ``module_user``         — Admin user in that org
- ``module_auth_headers`` — JWT ``Authorization`` headers for that user
- ``module_client``       — FastAPI ``TestClient`` (shares the root ``client``)

The fixtures are **opt-in**: they activate only when the marker is present.
Tests that do not carry ``@pytest.mark.module(...)`` never see them.

Usage::

    @pytest.mark.module('equipment')
    def test_create_asset(module_client, module_auth_headers):
        resp = module_client.post(
            '/api/v1/equipment/assets',
            json={...},
            headers=module_auth_headers,
        )
        assert resp.status_code == 201
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.models.organization import Organization
    from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_module_name(request: pytest.FixtureRequest) -> str:
    """Extract module name from the closest ``@pytest.mark.module('name')`` marker.

    Raises ``pytest.Skipped`` when no marker is found so that misuse is
    immediately visible rather than silently producing ``None``.
    """
    marker = request.node.get_closest_marker('module')
    if not marker:
        pytest.skip('Test is not marked with @pytest.mark.module — fixture unavailable')
    # Module name is the first positional argument: @pytest.mark.module('equipment')
    args = marker.args
    if not args:
        pytest.skip('@pytest.mark.module() requires a module name argument')
    return str(args[0])


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def module_org(
    request: pytest.FixtureRequest, db_session: Session
) -> Generator[Organization]:  # noqa: F821
    """Organization with the test's ``@pytest.mark.module`` module enabled.

    Always includes the core modules (``core``, ``items``, ``locations``,
    ``categories``) plus the module specified in the marker.
    """
    from app.models.organization import Organization

    module_name = _get_module_name(request)
    org = Organization(
        name=f'{module_name.capitalize()} Test Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'locations', 'categories', module_name],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    yield org


@pytest.fixture
def module_user(module_org: Organization, db_session: Session) -> Generator[User]:  # noqa: F821
    """Admin user in the ``module_org`` organization."""
    from app.models.user import User
    from app.services.auth_service import get_password_hash

    user = User(
        email=f'module_test_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Module Test User',
        organization_id=module_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user


@pytest.fixture
def module_auth_headers(module_user: User) -> dict[str, str]:  # noqa: F821
    """JWT ``Authorization`` headers for ``module_user``."""
    from app.services.token_service import create_access_token

    access_token = create_access_token(data={'sub': str(module_user.id)})
    return {'Authorization': f'Bearer {access_token}'}


@pytest.fixture
def module_client(client: TestClient) -> TestClient:
    """FastAPI ``TestClient`` for module tests.

    Re-uses the root ``client`` fixture (same dependency-overrides wiring).
    Pass ``module_auth_headers`` as ``headers=`` to authenticate requests.
    """
    return client
