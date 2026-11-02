"""Tests for core_api.permissions and core_api.roles namespaces.

These tests cover the DB-backed permission/role surface that modules
use to check and assign permissions without touching the role models
directly. The ``UserContextDTO.has_permission`` path is covered by
existing auth tests; this suite focuses on the CoreAPI contract.

Contract for permissions:
    - check_async answers what ``UserContextDTO.has_permission`` would for
      that user: administrators bypass; a user holding custom role rows is
      judged by those rows alone; a user holding none falls back to their
      built-in level, which is where a module manifest's ``default_roles``
      land.
    - Both methods consult the DB fresh (NOT the cached UserContextDTO)
      so admin tooling can check permissions after role changes without
      forcing the user to log out and back in.

Contract for roles:
    - list_for_user_async returns all roles (system + org-scoped) the
      user holds in the given organization.
    - assign_async links a user to a role; idempotent (re-assigning an
      existing link is a no-op rather than an error).
    - assign_async validates that the role belongs to the given
      organization (org-scoping guard) — assigning a role from org A
      to a user in org B raises ValueError.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.contracts import RoleDTO, SystemPermission
from app.core.public_api import core_api
from app.models.role import Role, UserRole
from app.services.permissions_service import check_user_permission_async

pytestmark = pytest.mark.integration


async def _make_role(
    db,
    organization_id,
    *,
    name: str,
    permissions: list[str],
    is_system: bool = False,
):
    """Insert a role via the async session, return the refreshed instance."""
    from sqlalchemy.orm import Session

    def _create(s: Session) -> Role:
        role = Role(
            organization_id=organization_id,
            name=name,
            permissions=permissions,
            is_system=is_system,
        )
        s.add(role)
        s.commit()
        s.refresh(role)
        return role

    return await db.run_sync(_create)


@pytest.mark.asyncio
class TestCorePermissionsAPI:
    """DB-backed permission checks (fresh, not cached)."""

    async def test_check_async_returns_true_for_user_with_permission(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user2,
    ):
        """User with role granting ITEMS_READ → check returns True."""
        db = real_async_db_session
        role = await _make_role(
            db,
            async_test_household.id,
            name='reader',
            permissions=['items:read'],
        )
        await db.run_sync(
            lambda s: s.add(UserRole(user_id=async_test_user2.id, role_id=role.id))
        )
        await db.commit()

        result = await check_user_permission_async(
            db,
            user_id=async_test_user2.id,
            organization_id=async_test_household.id,
            permission=SystemPermission.ITEMS_READ,
        )
        assert result is True

    async def test_check_async_bypasses_for_an_administrator(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """An administrator holds everything, exactly as the guards read it.

        ``UserContextDTO.has_permission`` returns True for them before it
        looks at any permission set; a fresh lookup that answered otherwise
        would report a lockout the API does not enforce.
        """
        db = real_async_db_session
        result = await check_user_permission_async(
            db,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            permission=SystemPermission.ORG_SETTINGS_WRITE,
        )
        assert result is True

    async def test_check_async_reads_the_builtin_level_when_no_role_row(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user2,
    ):
        """A member with no role row still holds what their level grants.

        The level is where the module manifests' ``default_roles`` land, so
        an organization that never created a custom role is not an
        organization where everybody holds nothing.
        """
        db = real_async_db_session
        result = await check_user_permission_async(
            db,
            user_id=async_test_user2.id,
            organization_id=async_test_household.id,
            permission=SystemPermission.ITEMS_READ,
        )
        assert result is True

    async def test_check_async_returns_false_for_a_stranger_to_the_org(
        self,
        real_async_db_session,
        async_test_household,
    ):
        """A user id that is not a member here holds nothing here."""
        db = real_async_db_session
        result = await check_user_permission_async(
            db,
            user_id=uuid4(),
            organization_id=async_test_household.id,
            permission=SystemPermission.ITEMS_READ,
        )
        assert result is False

    async def test_check_async_returns_false_for_user_without_permission(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user2,
    ):
        """User with no role granting ORG_SETTINGS_WRITE → check returns False."""
        db = real_async_db_session
        role = await _make_role(
            db,
            async_test_household.id,
            name='reader',
            permissions=['items:read'],
        )
        await db.run_sync(
            lambda s: s.add(UserRole(user_id=async_test_user2.id, role_id=role.id))
        )
        await db.commit()

        result = await check_user_permission_async(
            db,
            user_id=async_test_user2.id,
            organization_id=async_test_household.id,
            permission=SystemPermission.ORG_SETTINGS_WRITE,
        )
        assert result is False

    async def test_check_async_returns_false_for_what_no_level_grants(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user2,
    ):
        """A member with no role row holds their level and nothing above it."""
        db = real_async_db_session
        result = await check_user_permission_async(
            db,
            user_id=async_test_user2.id,
            organization_id=async_test_household.id,
            permission=SystemPermission.ORG_SETTINGS_WRITE,
        )
        assert result is False

    async def test_check_async_accepts_custom_permission_string(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user2,
    ):
        """Module-registered custom permission (not in SystemPermission enum)."""
        db = real_async_db_session
        role = await _make_role(
            db,
            async_test_household.id,
            name='cashier',
            permissions=['pos:sell'],
        )
        await db.run_sync(
            lambda s: s.add(UserRole(user_id=async_test_user2.id, role_id=role.id))
        )
        await db.commit()

        result = await check_user_permission_async(
            db,
            user_id=async_test_user2.id,
            organization_id=async_test_household.id,
            permission='pos:sell',
        )
        assert result is True

    async def test_check_async_does_not_leak_other_orgs_permissions(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user2,
    ):
        """A role in another org granting a permission does NOT satisfy
        check_async for the user's own org."""
        db = real_async_db_session
        from ._core_api_helpers import make_other_org

        other_org = await db.run_sync(make_other_org)
        other_role = await _make_role(
            db,
            other_org.id,
            name='other-cashier',
            permissions=['pos:sell'],
        )
        await db.run_sync(
            lambda s: s.add(
                UserRole(user_id=async_test_user2.id, role_id=other_role.id)
            )
        )
        await db.commit()

        # Check is scoped to the user's own org: the grant over there leaves
        # them with their level here, which does not sell anything.
        result = await check_user_permission_async(
            db,
            user_id=async_test_user2.id,
            organization_id=async_test_household.id,
            permission='pos:sell',
        )
        assert result is False


@pytest.mark.asyncio
class TestCoreRolesAPI:
    """Role listing + assignment via CoreAPI."""

    async def test_list_for_user_async_returns_assigned_roles(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """User with 2 roles → list returns both as DTOs."""
        db = real_async_db_session
        role_a = await _make_role(
            db,
            async_test_household.id,
            name='reader',
            permissions=['items:read'],
        )
        role_b = await _make_role(
            db,
            async_test_household.id,
            name='writer',
            permissions=['items:write'],
        )
        for r in (role_a, role_b):
            await db.run_sync(
                lambda s, _r=r: s.add(
                    UserRole(user_id=async_test_user.id, role_id=_r.id)
                )
            )
        await db.commit()

        result = await core_api.roles.list_for_user_async(
            db, async_test_household.id, async_test_user.id
        )

        assert len(result) == 2
        assert all(isinstance(r, RoleDTO) for r in result)
        names = {r.name for r in result}
        assert names == {'reader', 'writer'}

    async def test_list_for_user_async_returns_empty_when_no_roles(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """User with no roles → empty list (never None)."""
        db = real_async_db_session
        result = await core_api.roles.list_for_user_async(
            db, async_test_household.id, async_test_user.id
        )
        assert result == []

    async def test_assign_async_creates_user_role_link(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Assigning a role makes it appear in list_for_user_async."""
        db = real_async_db_session
        role = await _make_role(
            db,
            async_test_household.id,
            name='admin-role',
            permissions=['items:read', 'items:write'],
        )

        await core_api.roles.assign_async(
            db,
            async_test_household.id,
            async_test_user.id,
            role.id,
            actor_user_id=async_test_user.id,
        )
        await db.commit()

        roles = await core_api.roles.list_for_user_async(
            db, async_test_household.id, async_test_user.id
        )
        assert any(r.id == role.id for r in roles)

    async def test_assign_async_is_idempotent(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Assigning the same role twice does not create duplicates and
        does not raise."""
        db = real_async_db_session
        role = await _make_role(
            db,
            async_test_household.id,
            name='dup-test',
            permissions=['items:read'],
        )

        for _ in range(3):
            await core_api.roles.assign_async(
                db,
                async_test_household.id,
                async_test_user.id,
                role.id,
                actor_user_id=async_test_user.id,
            )
        await db.commit()

        roles = await core_api.roles.list_for_user_async(
            db, async_test_household.id, async_test_user.id
        )
        assert len(roles) == 1
        assert roles[0].id == role.id

    async def test_assign_async_rejects_role_from_different_org(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Assigning a role that belongs to another org → ValueError."""
        db = real_async_db_session
        from ._core_api_helpers import make_other_org

        other_org = await db.run_sync(make_other_org)
        other_role = await _make_role(
            db,
            other_org.id,
            name='other-admin',
            permissions=['items:read'],
        )

        with pytest.raises(ValueError, match='organization'):
            await core_api.roles.assign_async(
                db,
                async_test_household.id,
                async_test_user.id,
                other_role.id,
                actor_user_id=async_test_user.id,
            )

    async def test_assign_async_for_unknown_role_raises_value_error(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Assigning a non-existent role_id → ValueError (not silent no-op)."""
        db = real_async_db_session
        with pytest.raises(ValueError, match='not found'):
            await core_api.roles.assign_async(
                db,
                async_test_household.id,
                async_test_user.id,
                uuid4(),
                actor_user_id=async_test_user.id,
            )

    async def test_dto_includes_permissions_list(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """RoleDTO.permissions surfaces the role's permission list."""
        db = real_async_db_session
        role = await _make_role(
            db,
            async_test_household.id,
            name='multi',
            permissions=['items:read', 'items:write', 'pos:sell'],
        )
        await db.run_sync(
            lambda s: s.add(UserRole(user_id=async_test_user.id, role_id=role.id))
        )
        await db.commit()

        roles = await core_api.roles.list_for_user_async(
            db, async_test_household.id, async_test_user.id
        )
        assert len(roles) == 1
        assert set(roles[0].permissions) == {'items:read', 'items:write', 'pos:sell'}
        assert roles[0].is_system is False
