"""Integration tests for RBAC enforcement.

Covers:
- require_permission() dependency returns 403 for users lacking the permission
- require_permission() allows users with the required permission
- Admin role bypasses all permission checks
- Item currency validation: create/update rejects currency != org currency
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import require_permission
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_org(db: Session, *, currency: str = 'PLN') -> Organization:
    org = Organization(name=f'RBAC Enf Org {uuid.uuid4().hex[:6]}', currency=currency)
    db.add(org)
    db.flush()
    return org


def _make_user(db: Session, org: Organization, *, role: str = 'user') -> User:
    user = User(
        email=f'rbac_enf_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=org.id,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_role(db: Session, org: Organization, perms: list[str]) -> Role:
    """A role belongs to an organisation — the column requires one."""
    role = Role(
        name=f'role_{uuid.uuid4().hex[:6]}',
        permissions=perms,
        is_system=False,
        organization_id=org.id,
    )
    db.add(role)
    db.flush()
    return role


def _assign(db: Session, user: User, role: Role) -> None:
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()


def _make_token(user: User) -> str:
    return create_access_token(data={'sub': str(user.id)})


def _auth(user: User) -> dict:
    return {'Authorization': f'Bearer {_make_token(user)}'}


# ── require_permission unit tests (pure dependency, no HTTP) ───────────────


@pytest.mark.asyncio
async def test_require_permission_allows_user_with_matching_permission() -> None:
    """require_permission passes when user context satisfies the requirement."""
    ctx = UserContextDTO(
        id=uuid.uuid4(),
        organization_id=None,
        role='user',
        permissions={SystemPermission.ITEMS_DELETE},
    )
    dep = require_permission(SystemPermission.ITEMS_DELETE)
    # Manually invoke the inner check function with the resolved context.
    await dep.dependency(user_context=ctx)  # should not raise


@pytest.mark.asyncio
async def test_require_permission_blocks_user_missing_permission() -> None:
    """require_permission raises HTTP 403 when user lacks the required permission."""
    from fastapi import HTTPException

    ctx = UserContextDTO(
        id=uuid.uuid4(),
        organization_id=None,
        role='user',
        permissions={SystemPermission.ITEMS_READ},
    )
    dep = require_permission(SystemPermission.ITEMS_DELETE)
    with pytest.raises(HTTPException) as exc_info:
        await dep.dependency(user_context=ctx)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_permission_admin_always_passes() -> None:
    """Admin role bypasses require_permission regardless of permissions set."""
    ctx = UserContextDTO(
        id=uuid.uuid4(),
        organization_id=None,
        role='admin',
        permissions=set(),  # empty — but admin bypasses
    )
    dep = require_permission(SystemPermission.ITEMS_DELETE)
    await dep.dependency(user_context=ctx)  # should not raise


@pytest.mark.asyncio
async def test_require_permission_module_string_permission() -> None:
    """require_permission works with custom module permission strings."""
    ctx = UserContextDTO(
        id=uuid.uuid4(),
        organization_id=None,
        role='user',
        permissions=set(),
        extra_permissions={'pos:sell'},
    )
    dep = require_permission('pos:sell')
    await dep.dependency(user_context=ctx)  # should not raise


# ── HTTP-level enforcement tests via API ──────────────────────────────────


@pytest.mark.integration
class TestItemDeletePermissionEnforcement:
    """require_permission enforcement tested through the real items endpoint."""

    def test_user_without_items_delete_cannot_delete(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """A user lacking items:delete gets HTTP 403 on DELETE /api/v1/items/{id}."""
        org = db_session.get(Organization, test_item.organization_id)
        restricted_user = _make_user(db_session, org, role='user')
        read_only_role = _make_role(
            db_session,
            org,
            [SystemPermission.ITEMS_READ.value, SystemPermission.ITEMS_WRITE.value],
        )
        _assign(db_session, restricted_user, read_only_role)
        db_session.commit()

        resp = client.delete(
            f'/api/v1/items/{test_item.id}', headers=_auth(restricted_user)
        )
        assert resp.status_code == 403

    def test_user_with_items_delete_can_delete(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """A user with items:delete gets 204 on DELETE /api/v1/items/{id}."""
        org = db_session.get(Organization, test_item.organization_id)
        power_user = _make_user(db_session, org, role='user')
        delete_role = _make_role(
            db_session,
            org,
            [
                SystemPermission.ITEMS_READ.value,
                SystemPermission.ITEMS_WRITE.value,
                SystemPermission.ITEMS_DELETE.value,
            ],
        )
        _assign(db_session, power_user, delete_role)
        db_session.commit()

        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=_auth(power_user))
        assert resp.status_code in (200, 204)

    def test_admin_can_always_delete(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """An admin user with role='admin' and no explicit DB roles can delete items."""
        org = db_session.get(Organization, test_item.organization_id)
        admin_user = _make_user(db_session, org, role='admin')
        # No DB roles assigned — relies on legacy fallback (admin gets all perms).
        db_session.commit()

        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=_auth(admin_user))
        assert resp.status_code in (200, 204)


# ──: purge requires ITEMS_PURGE, not just ITEMS_DELETE ────────────────


@pytest.mark.integration
class TestItemPurgePermissionEnforcement:
    """items:delete covers archiving; the irreversible purge needs items:purge.

    splits the two: someone who can archive must not automatically be
       able to permanently delete. Admin bypass still applies.
    """

    def test_user_with_items_delete_only_can_archive_but_not_purge(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """items:delete grants archiving (204) but the purge stays 403."""
        org = db_session.get(Organization, test_item.organization_id)
        power_user = _make_user(db_session, org, role='user')
        delete_role = _make_role(
            db_session,
            org,
            [
                SystemPermission.ITEMS_READ.value,
                SystemPermission.ITEMS_WRITE.value,
                SystemPermission.ITEMS_DELETE.value,
            ],
        )
        _assign(db_session, power_user, delete_role)
        db_session.commit()

        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=_auth(power_user))
        assert resp.status_code in (200, 204)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=_auth(power_user)
        )
        assert resp.status_code == 403

    def test_user_with_items_purge_can_purge(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """A role holding items:purge passes the purge gate."""
        org = db_session.get(Organization, test_item.organization_id)
        purge_user = _make_user(db_session, org, role='user')
        purge_role = _make_role(
            db_session,
            org,
            [
                SystemPermission.ITEMS_READ.value,
                SystemPermission.ITEMS_WRITE.value,
                SystemPermission.ITEMS_DELETE.value,
                SystemPermission.ITEMS_PURGE.value,
            ],
        )
        _assign(db_session, purge_user, purge_role)
        db_session.commit()

        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=_auth(purge_user))
        assert resp.status_code in (200, 204)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=_auth(purge_user)
        )
        assert resp.status_code in (200, 204)

    def test_admin_can_always_purge(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """An admin with no explicit DB roles can purge (admin bypass)."""
        org = db_session.get(Organization, test_item.organization_id)
        admin_user = _make_user(db_session, org, role='admin')
        db_session.commit()

        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=_auth(admin_user))
        assert resp.status_code in (200, 204)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=_auth(admin_user)
        )
        assert resp.status_code in (200, 204)


# ── Stock-mutating endpoints must require ITEMS_WRITE ──────────────────────


@pytest.mark.integration
class TestItemMutatePermissionEnforcement:
    """move / discard / bulk mutate stock (the records) and must require
    ITEMS_WRITE, matching consume/quantity/delete.  A user holding only
    ITEMS_READ is denied (regression guard)."""

    @staticmethod
    def _read_only_user(db_session: Session, test_item) -> User:
        org = db_session.get(Organization, test_item.organization_id)
        user = _make_user(db_session, org, role='user')
        _assign(
            db_session,
            user,
            _make_role(db_session, org, [SystemPermission.ITEMS_READ.value]),
        )
        db_session.commit()
        return user

    def test_move_requires_items_write(
        self, client: TestClient, db_session: Session, test_item, test_storage_location
    ) -> None:
        user = self._read_only_user(db_session, test_item)
        resp = client.patch(
            f'/api/v1/items/{test_item.id}/move',
            json={'to_location_id': str(test_storage_location.id)},
            headers=_auth(user),
        )
        assert resp.status_code == 403

    def test_discard_requires_items_write(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        user = self._read_only_user(db_session, test_item)
        resp = client.patch(
            f'/api/v1/items/{test_item.id}/discard',
            json={'quantity': 1, 'reason': 'expired'},
            headers=_auth(user),
        )
        assert resp.status_code == 403

    def test_bulk_requires_items_write(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        user = self._read_only_user(db_session, test_item)
        resp = client.patch(
            '/api/v1/items/bulk',
            json={'item_ids': [str(test_item.id)], 'update_data': {'name': 'X'}},
            headers=_auth(user),
        )
        assert resp.status_code == 403


# ── Item currency validation tests ────────────────────────────────────────


@pytest.mark.integration
class TestItemCurrencyValidation:
    """create_item and update_item reject currency != org currency."""

    def test_create_item_with_mismatched_currency_returns_error(
        self,
        client: TestClient,
        db_session: Session,
        test_storage_location,
    ) -> None:
        """POST /api/v1/items with currency != org currency returns HTTP 400/422."""
        org = db_session.get(Organization, test_storage_location.organization_id)
        org.currency = 'PLN'
        db_session.commit()

        # Use the existing admin test_user fixture via auth_headers approach.
        from app.models.user import User as UserModel

        admin = db_session.scalars(
            select(UserModel).where(
                UserModel.organization_id == org.id, UserModel.role == 'admin'
            )
        ).first()
        assert admin is not None, 'Admin user fixture must exist in this test context'

        payload = {
            'name': 'Foreign Wine',
            'location_id': str(test_storage_location.id),
            'currency': 'EUR',  # ← mismatch with org PLN
        }
        resp = client.post('/api/v1/items', json=payload, headers=_auth(admin))
        assert resp.status_code in (400, 422, 500), (
            f'Expected error for currency mismatch, got {resp.status_code}: {resp.text}'
        )

    def test_create_item_with_matching_currency_succeeds(
        self,
        client: TestClient,
        db_session: Session,
        test_storage_location,
    ) -> None:
        """POST /api/v1/items with currency == org currency succeeds."""
        org = db_session.get(Organization, test_storage_location.organization_id)
        org.currency = 'PLN'
        db_session.commit()

        from app.models.user import User as UserModel

        admin = db_session.scalars(
            select(UserModel).where(
                UserModel.organization_id == org.id, UserModel.role == 'admin'
            )
        ).first()
        assert admin is not None

        payload = {
            'name': 'Local Beer',
            'location_id': str(test_storage_location.id),
            'currency': 'PLN',  # ← matches org currency
        }
        resp = client.post('/api/v1/items', json=payload, headers=_auth(admin))
        assert resp.status_code in (200, 201), (
            f'Expected success for matching currency, got {resp.status_code}: {resp.text}'
        )

    def test_update_item_with_mismatched_currency_returns_error(
        self,
        client: TestClient,
        db_session: Session,
        test_item,
    ) -> None:
        """PUT /api/v1/items/{id} with currency != org currency returns error."""
        org = db_session.get(Organization, test_item.organization_id)
        org.currency = 'PLN'
        db_session.commit()

        from app.models.user import User as UserModel

        admin = db_session.scalars(
            select(UserModel).where(
                UserModel.organization_id == org.id, UserModel.role == 'admin'
            )
        ).first()
        assert admin is not None

        resp = client.put(
            f'/api/v1/items/{test_item.id}',
            json={'currency': 'USD'},  # ← mismatch
            headers=_auth(admin),
        )
        assert resp.status_code in (400, 422, 500), (
            f'Expected error for currency mismatch, got {resp.status_code}: {resp.text}'
        )
