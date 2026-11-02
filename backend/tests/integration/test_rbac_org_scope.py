"""Roles must not leak across organizations (step 5).

``user_roles`` has no ``organization_id``, so loading a user's roles by user id
alone gave a member of several organizations the union of their permissions in
every one of them. These tests pin the scope: a role belongs to one
organization, grants there and nowhere else.

There used to be an exception — a role with no organization at all, read as
belonging to every one of them by the roles list, the permission check and a
user's own roles alike. One such row was a grant across the whole
installation. The column refuses it now, and the case below says so.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.contracts import SystemPermission
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

DELETE_PERMS = [
    SystemPermission.ITEMS_READ.value,
    SystemPermission.ITEMS_WRITE.value,
    SystemPermission.ITEMS_DELETE.value,
]


def _make_org(db: Session) -> Organization:
    org = Organization(name=f'Scope Org {uuid.uuid4().hex[:6]}', currency='PLN')
    db.add(org)
    db.flush()
    return org


def _make_user(db: Session, org: Organization) -> User:
    user = User(
        email=f'scope_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=org.id,
        role='user',
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_role(db: Session, perms: list[str], org_id) -> Role:
    """A role scoped to *org_id* — the only kind there is."""
    role = Role(
        name=f'scoped_{uuid.uuid4().hex[:6]}',
        permissions=perms,
        is_system=False,
        organization_id=org_id,
    )
    db.add(role)
    db.flush()
    return role


def _assign(db: Session, user: User, role: Role) -> None:
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
class TestRoleOrganizationScope:
    def test_role_from_another_organization_grants_nothing(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """The regression: permission earned in org B must not apply in org A."""
        home_org = db_session.get(Organization, test_item.organization_id)
        user = _make_user(db_session, home_org)
        other_org = _make_org(db_session)
        _assign(db_session, user, _make_role(db_session, DELETE_PERMS, other_org.id))
        db_session.commit()

        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=_auth(user))

        assert resp.status_code == 403

    def test_role_from_the_same_organization_still_grants(
        self, client: TestClient, db_session: Session, test_item
    ) -> None:
        """Control: the scope filter must not lock out legitimate roles."""
        home_org = db_session.get(Organization, test_item.organization_id)
        user = _make_user(db_session, home_org)
        _assign(db_session, user, _make_role(db_session, DELETE_PERMS, home_org.id))
        db_session.commit()

        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=_auth(user))

        assert resp.status_code in (200, 204)

    def test_a_role_belonging_to_no_organization_cannot_be_written(
        self, db_session: Session
    ) -> None:
        """The row that used to grant its permissions in every organization.

        Three queries read ``organization_id IS NULL`` as "belongs to all of
        them". Nothing in the app writes such a row — and nothing needs to,
        because the four built-in levels are not rows — so the column says it
        rather than every caller remembering to.
        """
        db_session.add(
            Role(
                name=f'global_{uuid.uuid4().hex[:6]}',
                permissions=DELETE_PERMS,
                is_system=True,
                organization_id=None,
            )
        )

        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
class TestRoleLinksFollowMembership:
    """``UserRole`` carries no organization, so a membership change
    used to leave the old grants in place, and a role could be granted to a
    member of another organization."""

    @staticmethod
    async def _org(db) -> Organization:
        org = Organization(name=f'Scope Org {uuid.uuid4().hex[:6]}', currency='PLN')
        db.add(org)
        await db.flush()
        return org

    @staticmethod
    async def _user(db, org: Organization) -> User:
        user = User(
            email=f'scope_{uuid.uuid4().hex[:8]}@test.com',
            hashed_password=get_password_hash('pass'),
            organization_id=org.id,
            role='user',
            is_active=True,
        )
        db.add(user)
        await db.flush()
        return user

    @staticmethod
    async def _role(db, perms: list[str], org_id) -> Role:
        role = Role(
            name=f'scoped_{uuid.uuid4().hex[:6]}',
            permissions=perms,
            is_system=False,
            organization_id=org_id,
        )
        db.add(role)
        await db.flush()
        return role

    async def test_changing_organization_drops_the_old_role_links(
        self, real_async_db_session
    ):
        from sqlalchemy import select as sa_select

        from app.models.organization import OrganizationInvitation
        from app.services._org_membership import join_organization

        db = real_async_db_session
        org_a = await self._org(db)
        org_b = await self._org(db)
        user = await self._user(db, org_a)
        inviter = await self._user(db, org_b)
        role_a = await self._role(db, DELETE_PERMS, org_a.id)
        role_b = await self._role(db, [SystemPermission.ORG_READ.value], org_b.id)
        db.add_all(
            [
                UserRole(user_id=user.id, role_id=role_a.id),
                UserRole(user_id=user.id, role_id=role_b.id),
                OrganizationInvitation(
                    organization_id=org_b.id,
                    code=f'{uuid.uuid4().int % 1000000:06d}',
                    created_by=inviter.id,
                    is_used=False,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                ),
            ]
        )
        await db.flush()
        invitation = await db.scalar(
            sa_select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == org_b.id
            )
        )

        await join_organization(db, invitation.code, user.id)

        remaining = {
            link.role_id
            for link in (
                await db.scalars(sa_select(UserRole).where(UserRole.user_id == user.id))
            ).all()
        }
        assert role_a.id not in remaining, (
            'a role granted in the organization the user left must not survive'
        )
        assert role_b.id in remaining, (
            'a role in the organization being joined is the one that applies'
        )

    async def test_assigning_a_role_to_a_member_of_another_org_is_refused(
        self, real_async_db_session
    ):
        from app.services.permissions_service import assign_role_async

        db = real_async_db_session
        org_a = await self._org(db)
        org_b = await self._org(db)
        outsider = await self._user(db, org_b)
        role_a = await self._role(db, DELETE_PERMS, org_a.id)

        with pytest.raises(ValueError, match='does not belong'):
            await assign_role_async(
                db,
                organization_id=org_a.id,
                user_id=outsider.id,
                role_id=role_a.id,
                actor_user_id=outsider.id,
            )

    async def test_another_organisations_role_cannot_be_rewritten(
        self, real_async_db_session
    ):
        from app.services.permissions_service import update_role_permissions_async

        db = real_async_db_session
        org_a = await self._org(db)
        org_b = await self._org(db)
        theirs = await self._role(db, [SystemPermission.ORG_READ.value], org_b.id)

        with pytest.raises(ValueError, match='different organization'):
            await update_role_permissions_async(
                db,
                organization_id=org_a.id,
                role_id=theirs.id,
                permissions=DELETE_PERMS,
            )
