"""the org-level allow_permanent_delete switch gates the purge.

The explicit ``organization.settings['allow_permanent_delete']`` wins; when
unset, the value is derived from the product profile — ``food_home`` (and
legacy orgs without a profile) keep the convenience, business profiles
(``equipment_wms``, ``clean_core``) start locked. A locked org gets 403 with
code ``PURGE_DISABLED`` even for admins.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization

pytestmark = pytest.mark.integration


def _set_flag_and_profile(
    db_session: Session, test_item, *, flag: bool | None, profile: str | None
) -> None:
    org = db_session.get(Organization, test_item.organization_id)
    assert org is not None
    if flag is None:
        org.settings = {}
    else:
        org.settings = {'allow_permanent_delete': flag}
    org.active_profile_id = profile
    db_session.commit()


def _archive(client: TestClient, auth_headers: dict[str, str], test_item) -> None:
    resp = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
    assert resp.status_code in (200, 204)


class TestPurgeOrgFlag:
    def test_explicit_false_blocks_purge_even_for_admin(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_item,
    ) -> None:
        """Flag off → 403 PURGE_DISABLED regardless of permissions."""
        _set_flag_and_profile(db_session, test_item, flag=False, profile='food_home')

        _archive(client, auth_headers, test_item)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json()['detail']['code'] == 'PURGE_DISABLED'

    def test_explicit_true_allows_purge(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_item,
    ) -> None:
        """Flag on → the purge proceeds."""
        _set_flag_and_profile(db_session, test_item, flag=True, profile='clean_core')

        _archive(client, auth_headers, test_item)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code in (200, 204)

    def test_food_home_profile_defaults_to_allowed(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_item,
    ) -> None:
        """No explicit flag + home profile → purge allowed."""
        _set_flag_and_profile(db_session, test_item, flag=None, profile='food_home')

        _archive(client, auth_headers, test_item)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code in (200, 204)

    def test_equipment_wms_profile_defaults_to_blocked(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_item,
    ) -> None:
        """No explicit flag + WMS profile → purge blocked."""
        _set_flag_and_profile(db_session, test_item, flag=None, profile='equipment_wms')

        _archive(client, auth_headers, test_item)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_clean_core_profile_defaults_to_blocked(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_item,
    ) -> None:
        """No explicit flag + clean_core profile → purge blocked."""
        _set_flag_and_profile(db_session, test_item, flag=None, profile='clean_core')

        _archive(client, auth_headers, test_item)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_legacy_org_without_profile_defaults_to_allowed(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_item,
    ) -> None:
        """No flag and no profile (pre-profile orgs) → purge allowed (backward compat)."""
        _set_flag_and_profile(db_session, test_item, flag=None, profile=None)

        _archive(client, auth_headers, test_item)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code in (200, 204)
