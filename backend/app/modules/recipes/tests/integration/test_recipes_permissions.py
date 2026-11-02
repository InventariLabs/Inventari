"""Permission enforcement on the recipes module endpoints.

The module router carried only ``require_module('recipes')``, so every member
of an organization could write everything in it. The manifest declared one
permission of its own, ``recipes:consume``, enforced in exactly one place —
which produced a rule nobody would choose: a read-only account could not
*cook* a recipe, because that consumes stock, but could *delete* it.

The guard is mounted once on the module router, as it already is in both
neighbours (``shopping_lists`` and ``maker``): safe methods need ``read``,
mutating ones need ``write``. These tests pin the boundary, not the endpoints.

Legacy installs keep working because the manifest hands the permissions to
the roles that already had the access, and the user context falls back to
those defaults for a member carrying no explicit role row.
"""

from __future__ import annotations

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/recipes'


@pytest.fixture
def rec_h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def rec_org(rec_h: ModuleTestHelper) -> Organization:
    return rec_h.create_org(
        'Recipes Permissions Org',
        ['core', 'items', 'categories', 'locations', 'recipes'],
    )


@pytest.fixture
def operator(rec_h: ModuleTestHelper, rec_org: Organization) -> User:
    """A plain member with no explicit role row — the legacy install shape."""
    return rec_h.create_user(rec_org, email='recipes-operator@example.com', role='user')


@pytest.fixture
def viewer(rec_h: ModuleTestHelper, rec_org: Organization) -> User:
    return rec_h.create_user(rec_org, email='recipes-viewer@example.com', role='viewer')


def _recipe_payload(name: str = 'Permission Test Recipe') -> dict[str, object]:
    return {'name': name, 'servings': 2, 'ingredients': []}


@pytest.mark.integration
class TestRecipesPermissions:
    def test_operator_without_role_row_keeps_write_access(
        self,
        client: TestClient,
        rec_h: ModuleTestHelper,
        operator: User,
    ) -> None:
        resp = client.post(
            BASE, headers=rec_h.get_auth_headers(operator), json=_recipe_payload()
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_viewer_reads_but_cannot_create(
        self,
        client: TestClient,
        rec_h: ModuleTestHelper,
        viewer: User,
    ) -> None:
        headers = rec_h.get_auth_headers(viewer)
        assert client.get(BASE, headers=headers).status_code == status.HTTP_200_OK

        resp = client.post(BASE, headers=headers, json=_recipe_payload())
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_viewer_cannot_change_or_remove_a_recipe_somebody_else_wrote(
        self,
        client: TestClient,
        rec_h: ModuleTestHelper,
        operator: User,
        viewer: User,
    ) -> None:
        created = client.post(
            BASE,
            headers=rec_h.get_auth_headers(operator),
            json=_recipe_payload('Somebody Elses Recipe'),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        recipe_id = created.json()['id']

        headers = rec_h.get_auth_headers(viewer)
        renamed = client.put(
            f'{BASE}/{recipe_id}', headers=headers, json={'name': 'Renamed'}
        )
        assert renamed.status_code == status.HTTP_403_FORBIDDEN, renamed.text

        deleted = client.delete(f'{BASE}/{recipe_id}', headers=headers)
        assert deleted.status_code == status.HTTP_403_FORBIDDEN, deleted.text

        bulk = client.post(
            f'{BASE}/bulk-delete', headers=headers, json={'recipe_ids': [recipe_id]}
        )
        assert bulk.status_code == status.HTTP_403_FORBIDDEN, bulk.text

    def test_viewer_cannot_create_a_collection_or_a_meal_plan(
        self,
        client: TestClient,
        rec_h: ModuleTestHelper,
        viewer: User,
    ) -> None:
        """The guard covers the sub-routers, not just the top-level CRUD."""
        headers = rec_h.get_auth_headers(viewer)

        collection = client.post(
            f'{BASE}/collections', headers=headers, json={'name': 'Weekend Dinners'}
        )
        assert collection.status_code == status.HTTP_403_FORBIDDEN, collection.text

        plan = client.post(
            f'{BASE}/meal-plans',
            headers=headers,
            json={'start_date': '2026-09-01', 'end_date': '2026-09-07'},
        )
        assert plan.status_code == status.HTTP_403_FORBIDDEN, plan.text

    def test_read_grant_alone_cannot_create(
        self,
        client: TestClient,
        rec_h: ModuleTestHelper,
        rec_org: Organization,
    ) -> None:
        user = rec_h.create_user(
            rec_org, email='recipes-readonly@example.com', role='user'
        )
        rec_h.grant_permissions(user, ['recipes:read'])
        headers = rec_h.get_auth_headers(user)

        assert client.get(BASE, headers=headers).status_code == status.HTTP_200_OK
        resp = client.post(BASE, headers=headers, json=_recipe_payload())
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_write_grant_alone_cannot_read(
        self,
        client: TestClient,
        rec_h: ModuleTestHelper,
        rec_org: Organization,
    ) -> None:
        user = rec_h.create_user(
            rec_org, email='recipes-writeonly@example.com', role='user'
        )
        rec_h.grant_permissions(user, ['recipes:write'])
        resp = client.get(BASE, headers=rec_h.get_auth_headers(user))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
