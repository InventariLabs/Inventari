"""``/auth/me`` carries the caller's permissions.

Frontend gating was admin-or-nothing because the profile endpoint never said
what a user may do: ``useHasPermission`` had no set to check and returned
``false`` for every non-admin. These tests pin the contract the hook reads.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.contracts import SystemPermission
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _make_user(db: Session, org: Organization, role: str = 'user') -> User:
    user = User(
        email=f'me_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=org.id,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _grant(db: Session, user: User, perms: list[str], org_id) -> None:
    role = Role(
        name=f'me_{uuid.uuid4().hex[:6]}',
        permissions=perms,
        is_system=False,
        organization_id=org_id,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _me(client: TestClient, user: User) -> list[str]:
    resp = client.get('/api/v1/auth/me', headers=_auth(user))
    assert resp.status_code == 200, resp.text
    return resp.json()['permissions']


@pytest.mark.integration
class TestAuthMePermissions:
    def test_a_granted_system_permission_is_reported(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        org = db_session.get(Organization, test_item.organization_id)
        user = _make_user(db_session, org)
        _grant(db_session, user, [SystemPermission.ITEMS_WRITE.value], org.id)
        db_session.commit()

        assert SystemPermission.ITEMS_WRITE.value in _me(client, user)

    def test_a_module_permission_string_is_reported(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """Module keys are plain strings in the same JSONB list, and must survive."""
        org = db_session.get(Organization, test_item.organization_id)
        user = _make_user(db_session, org)
        _grant(db_session, user, ['approvals:approve'], org.id)
        db_session.commit()

        assert 'approvals:approve' in _me(client, user)

    def test_a_user_with_no_roles_gets_the_legacy_role_defaults(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """Role rows are rare in practice; most users fall back to ``User.role``.

        That fallback must be reflected here, or the UI would hide reads the
        API allows. What it must not do is hand out writes nobody granted.
        """
        org = db_session.get(Organization, test_item.organization_id)
        user = _make_user(db_session, org)
        db_session.commit()

        permissions = _me(client, user)

        assert SystemPermission.ITEMS_READ.value in permissions
        assert SystemPermission.ITEMS_DELETE.value not in permissions
        assert SystemPermission.SYSTEM_CONFIG_WRITE.value not in permissions

    def test_a_permission_from_another_org_is_not_reported(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """The org-scope fix must hold here too, or the UI leaks the other org."""
        org = db_session.get(Organization, test_item.organization_id)
        other = Organization(name=f'Other {uuid.uuid4().hex[:6]}', currency='PLN')
        db_session.add(other)
        db_session.flush()
        user = _make_user(db_session, org)
        _grant(db_session, user, [SystemPermission.ITEMS_DELETE.value], other.id)
        db_session.commit()

        assert SystemPermission.ITEMS_DELETE.value not in _me(client, user)

    def test_an_admin_sees_the_whole_catalog(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """Admins bypass permission checks server-side; the UI must not disagree."""
        org = db_session.get(Organization, test_item.organization_id)
        admin = _make_user(db_session, org, role='admin')
        db_session.commit()

        permissions = _me(client, admin)

        assert SystemPermission.SYSTEM_CONFIG_WRITE.value in permissions
        assert 'maker:write' in permissions, 'module permissions belong here too'
