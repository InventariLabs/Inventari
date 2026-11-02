"""The guards that turned nine manifest declarations into real restrictions.

Sixteen permission keys reached the roles matrix without a single enforcement
point: an administrator could tick and untick them all day without changing
what anybody could do. These cases pin the boundary each module now has, and
the compatibility that keeps a legacy install working — a member with no role
row still resolves the module defaults the manifest hands to their role name.

One case per module rather than per endpoint, deliberately: the guard is
mounted on the module router, so it covers every endpoint of that module
including the ones added later. Testing endpoints would test the mounting
twice and the contract not at all.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

BASE_MODULES = ['core', 'items', 'locations', 'categories']

#: module → (a GET path, a POST path, the POST body)
#: The write path must actually accept POST: FastAPI matches the method before
#: it resolves dependencies, so a 405 would pass a guard test that never ran
#: the guard.
GUARDED = {
    'equipment': ('/api/v1/equipment/assets', '/api/v1/equipment/models', {}),
    'maker': ('/api/v1/maker/recipes', '/api/v1/maker/recipes', {}),
    'shopping_lists': ('/api/v1/shopping-lists', '/api/v1/shopping-lists', {}),
    'stock_takes': ('/api/v1/stock-takes', '/api/v1/stock-takes', {}),
}


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


def _org(h: ModuleTestHelper, module: str) -> Organization:
    return h.create_org(f'{module} guard org', [*BASE_MODULES, module])


def _member(h: ModuleTestHelper, org: Organization, grants: list[str]) -> User:
    """A member whose permissions come from a role row and nothing else."""
    user = h.create_user(org, email=f'member-{org.name}@example.com', role='user')
    h.grant_permissions(user, grants)
    return user


@pytest.mark.integration
@pytest.mark.parametrize('module', sorted(GUARDED))
class TestReadWriteGuards:
    def test_read_grant_alone_cannot_write(
        self, client: TestClient, h: ModuleTestHelper, module: str
    ) -> None:
        org = _org(h, module)
        read_path, write_path, payload = GUARDED[module]
        user = _member(h, org, [f'{module}:read'])
        headers = h.get_auth_headers(user)

        assert client.get(read_path, headers=headers).status_code == status.HTTP_200_OK

        resp = client.post(write_path, headers=headers, json=payload)
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_no_grant_at_all_cannot_read(
        self, client: TestClient, h: ModuleTestHelper, module: str
    ) -> None:
        org = _org(h, module)
        read_path, _, _ = GUARDED[module]
        # A role row that grants something unrelated: the point is that the
        # row exists, so no manifest fallback applies.
        user = _member(h, org, ['items:read'])

        resp = client.get(read_path, headers=h.get_auth_headers(user))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_member_without_a_role_row_keeps_working(
        self, client: TestClient, h: ModuleTestHelper, module: str
    ) -> None:
        """The legacy install shape — permissions resolved from the manifest."""
        org = _org(h, module)
        read_path, _, _ = GUARDED[module]
        user = h.create_user(org, email=f'legacy-{module}@example.com', role='user')

        resp = client.get(read_path, headers=h.get_auth_headers(user))
        assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestReadOnlyModuleGuard:
    """Analytics has no mutating endpoint, so it carries a single read key."""

    def test_stats_needs_its_read_grant(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = _org(h, 'stats')
        denied = _member(h, org, ['items:read'])
        assert (
            client.get(
                '/api/v1/stats/overview', headers=h.get_auth_headers(denied)
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )

        allowed = h.create_user(org, email='stats-ok@example.com', role='user')
        h.grant_permissions(allowed, ['stats:read'])
        assert (
            client.get(
                '/api/v1/stats/overview', headers=h.get_auth_headers(allowed)
            ).status_code
            == status.HTTP_200_OK
        )


@pytest.mark.integration
class TestPointwiseGuards:
    """Where the HTTP method does not tell the truth about the effect.

    Both vision endpoints are POSTs that only read — they send an image to a
    metered model and return what it saw — so the read/write pair would name a
    write permission neither of them uses.
    """

    def test_vision_extract_needs_its_own_grant(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = _org(h, 'vision')
        user = _member(h, org, ['items:read'])

        resp = client.post(
            '/api/v1/vision/extract',
            headers=h.get_auth_headers(user),
            files={'images': ('label.jpg', b'not-an-image', 'image/jpeg')},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_cooking_from_stock_needs_the_consume_grant(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        """Everything before the final step is a draft; this one moves stock."""
        org = _org(h, 'recipes')
        user = _member(h, org, ['items:read'])

        resp = client.post(
            '/api/v1/recipes/00000000-0000-0000-0000-000000000000'
            '/picking/00000000-0000-0000-0000-000000000000/complete',
            headers=h.get_auth_headers(user),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
