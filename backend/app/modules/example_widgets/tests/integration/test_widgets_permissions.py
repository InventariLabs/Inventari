"""Permission enforcement on the reference module.

The module that module authors copy from mounted `require_module` and nothing
else, and its manifest declared no permissions at all. Measured with a viewer
account: `POST /example-widgets` answered 201 and `DELETE` answered 204.

The module itself is a demonstration and holds nobody's data. The weight of
this is that it is the template: it taught mounting a router with no
permission gate, and three holes of exactly that shape were found in one
review. Its neighbours already do it right — `shopping_lists` and `maker`
mount `require_read_write` on the module router — so the reference is the one
place that was teaching the wrong lesson.

Mounted on the router rather than per endpoint, deliberately: that covers the
endpoints added later, which is the half a per-endpoint guard always loses.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

import app.modules.example_widgets.models  # noqa: F401
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/example-widgets'


@pytest.fixture
def helper(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def perm_org(helper: ModuleTestHelper) -> Organization:
    return helper.create_org(
        'Widget Permissions Org',
        ['core', 'items', 'locations', 'categories', 'example_widgets'],
    )


@pytest.fixture
def viewer(helper: ModuleTestHelper, perm_org: Organization) -> User:
    return helper.create_user(
        perm_org, email='widget-viewer@example.com', role='viewer'
    )


@pytest.fixture
def operator(helper: ModuleTestHelper, perm_org: Organization) -> User:
    """A plain member with no explicit role row — the legacy install shape."""
    return helper.create_user(
        perm_org, email='widget-operator@example.com', role='user'
    )


@pytest.mark.integration
class TestWidgetPermissions:
    def test_a_viewer_reads(
        self, client: TestClient, helper: ModuleTestHelper, viewer: User
    ) -> None:
        response = client.get(BASE, headers=helper.get_auth_headers(viewer))

        assert response.status_code == status.HTTP_200_OK

    def test_a_viewer_cannot_create(
        self, client: TestClient, helper: ModuleTestHelper, viewer: User
    ) -> None:
        response = client.post(
            BASE,
            headers=helper.get_auth_headers(viewer),
            json={'name': 'Sprocket', 'color': 'blue', 'quantity': 1},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_viewer_cannot_delete(
        self, client: TestClient, helper: ModuleTestHelper, viewer: User, operator: User
    ) -> None:
        # The half the interface had already noticed: 'Add Widget' was
        # disabled for a viewer and 'Delete' was not.
        created = client.post(
            BASE,
            headers=helper.get_auth_headers(operator),
            json={'name': 'Sprocket', 'color': 'blue', 'quantity': 1},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        response = client.delete(
            f'{BASE}/{created.json()["id"]}',
            headers=helper.get_auth_headers(viewer),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_viewer_cannot_update(
        self, client: TestClient, helper: ModuleTestHelper, viewer: User, operator: User
    ) -> None:
        created = client.post(
            BASE,
            headers=helper.get_auth_headers(operator),
            json={'name': 'Sprocket', 'color': 'blue', 'quantity': 1},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        response = client.patch(
            f'{BASE}/{created.json()["id"]}',
            headers=helper.get_auth_headers(viewer),
            json={'quantity': 9},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_member_with_no_role_row_still_writes(
        self, client: TestClient, helper: ModuleTestHelper, operator: User
    ) -> None:
        # Gating a module that never gated anything must not lock out the
        # installs that already use it: the manifest hands the keys to the
        # roles that already had the access, and the user context falls back
        # to those defaults when a member carries no explicit role row.
        response = client.post(
            BASE,
            headers=helper.get_auth_headers(operator),
            json={'name': 'Sprocket', 'color': 'green', 'quantity': 2},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
