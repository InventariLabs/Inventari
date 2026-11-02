"""Integration tests for the RBAC system.

Covers:
- DB-backed roles with JSONB permissions
- Multi-role users get union of permissions
- Legacy fallback when no DB roles are assigned
- has_permission() with SystemPermission enum and plain strings
- ModuleRegistry.register_permission_defs() / get_all_permissions()
- Org-scoped roles are isolated from system-wide roles
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.module_manifest_schema import PermissionDef
from app.core.module_registry import module_registry
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.permissions_service import resolve_permission_strings_async

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_org(db, *, name='RBAC Org'):
    org = Organization(name=name)
    db.add(org)
    db.flush()
    return org


def _make_user(db, org, *, role='user', suffix=''):
    user = User(
        email=f'rbac_{role}_{suffix or id(org)}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=org.id,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_role(db, name, permissions, *, is_system=False, org):
    """A role always belongs to an organisation — the column requires one."""
    role = Role(
        name=name,
        permissions=permissions,
        is_system=is_system,
        organization_id=org.id,
    )
    db.add(role)
    db.flush()
    return role


def _assign(db, user, role):
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()


def _load_roles(db, user):
    return list(
        db.scalars(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        ).all()
    )


# ── DB schema / query tests ────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
class TestRbacDbSchema:
    """Tests that require DB access for role/user/permission operations."""

    async def test_admin_db_role_contains_all_system_permissions(
        self, real_async_db_session: AsyncSession
    ):
        """A role with all SystemPermission values stores and retrieves them correctly."""

        def _run(db):
            org = _make_org(db)
            user = _make_user(db, org, role='admin')
            admin_role = _make_role(
                db,
                'admin',
                [p.value for p in SystemPermission],
                is_system=True,
                org=org,
            )
            _assign(db, user, admin_role)
            db.commit()

            roles = _load_roles(db, user)
            assert len(roles) == 1
            assert set(roles[0].permissions) == {p.value for p in SystemPermission}

        await real_async_db_session.run_sync(_run)

    async def test_user_with_multiple_roles_gets_union_of_permissions(
        self, real_async_db_session: AsyncSession
    ):
        """User assigned to two roles receives the union of both permission sets."""

        def _run(db):
            org = _make_org(db)
            user = _make_user(db, org, suffix='multi')
            role_a = _make_role(
                db, 'role_a_multi', ['items:read', 'categories:read'], org=org
            )
            role_b = _make_role(
                db, 'role_b_multi', ['items:write', 'locations:read'], org=org
            )
            _assign(db, user, role_a)
            _assign(db, user, role_b)
            db.commit()

            roles = _load_roles(db, user)
            merged: set[str] = set()
            for r in roles:
                merged.update(r.permissions)

            assert merged == {
                'items:read',
                'categories:read',
                'items:write',
                'locations:read',
            }

        await real_async_db_session.run_sync(_run)

    async def test_org_scoped_role_is_isolated_per_organisation(
        self, real_async_db_session: AsyncSession
    ):
        """An org-scoped role belongs to one org and is independent of system roles."""

        def _run(db):
            org = _make_org(db, name='HoReCa Ltd')
            user = _make_user(db, org, suffix='cashier')
            cashier = _make_role(db, 'cashier', ['items:read', 'items:write'], org=org)
            _assign(db, user, cashier)
            db.commit()

            roles = _load_roles(db, user)
            assert len(roles) == 1
            assert roles[0].organization_id == org.id
            assert roles[0].name == 'cashier'
            assert set(roles[0].permissions) == {'items:read', 'items:write'}

        await real_async_db_session.run_sync(_run)

    async def test_system_role_flag_persists(self, real_async_db_session: AsyncSession):
        """is_system=True is stored and read back correctly."""

        def _run(db):
            org = _make_org(db)
            role = _make_role(db, 'sysrole', ['admin:access'], is_system=True, org=org)
            db.commit()
            db.expire(role)

            loaded = db.scalars(select(Role).where(Role.id == role.id)).one()
            assert loaded.is_system is True

        await real_async_db_session.run_sync(_run)

    async def test_admin_without_db_roles_holds_the_whole_catalogue(
        self, real_async_db_session: AsyncSession
    ):
        """An admin with no role row resolves to every permission the app knows.

        The subject is ``resolve_permission_strings_async`` — the one place
        both paths meet, the session context built at the door and the fresh
        lookup about somebody off the request. The version of this test that
        stood here until now copied the fallback branch into its own body and
        asserted against the copy, so it stayed green while the real mapping
        moved out from under it: the copy gave an admin the 15 system
        permissions, where the live resolver gives the whole catalogue —
        43 keys, because the modules' manifests are part of the answer.
        """
        ids: dict[str, uuid.UUID] = {}

        def _seed(db):
            org = _make_org(db)
            user = _make_user(db, org, role='admin', suffix='legacy_admin')
            db.commit()
            assert _load_roles(db, user) == []  # the fallback is what answers
            ids['user'], ids['org'] = user.id, org.id

        await real_async_db_session.run_sync(_seed)

        held = await resolve_permission_strings_async(
            real_async_db_session,
            user_id=ids['user'],
            organization_id=ids['org'],
            base_role='admin',
        )

        assert SystemPermission.ADMIN_ACCESS.value in held
        assert SystemPermission.SYSTEM_CONFIG_WRITE.value in held
        # Every system permission, plus the modules' on top — an admin screen
        # showing less than the API will act on lies about the account.
        assert {p.value for p in SystemPermission} <= held
        assert len(held) > len(SystemPermission)

    async def test_member_without_db_roles_holds_their_level_not_administration(
        self, real_async_db_session: AsyncSession
    ):
        """A member with no role row resolves to their base level, minus administration.

        Same subject, same reason as the test above: the mapping this asserts
        belongs to ``builtin_role_permissions``, not to a copy kept here. A
        member holds 30 keys today, not the 5 the copy named — filing things
        (categories, storages, partners) is part of the level.
        """
        ids: dict[str, uuid.UUID] = {}

        def _seed(db):
            org = _make_org(db)
            user = _make_user(db, org, suffix='legacy_user')
            db.commit()
            assert _load_roles(db, user) == []
            ids['user'], ids['org'] = user.id, org.id

        await real_async_db_session.run_sync(_seed)

        held = await resolve_permission_strings_async(
            real_async_db_session,
            user_id=ids['user'],
            organization_id=ids['org'],
            base_role='user',
        )

        assert SystemPermission.ITEMS_READ.value in held
        assert SystemPermission.ITEMS_WRITE.value in held
        # Filing is not administration: the member writes what they put away
        # and reads nothing about the system.
        assert SystemPermission.CATEGORIES_WRITE.value in held
        assert SystemPermission.ADMIN_ACCESS.value not in held
        assert SystemPermission.SYSTEM_CONFIG_WRITE.value not in held


# ── UserContextDTO unit tests ──────────────────────────────────────────────


@pytest.mark.integration
class TestUserContextDto:
    """Pure unit tests — no DB access needed."""

    def test_has_permission_with_system_permission_enum(self):
        """has_permission() returns True for permissions in the set, False otherwise."""
        ctx = UserContextDTO(
            id=uuid.uuid4(),
            organization_id=None,
            role='user',
            permissions={SystemPermission.ITEMS_READ, SystemPermission.CATEGORIES_READ},
        )
        assert ctx.has_permission(SystemPermission.ITEMS_READ) is True
        assert ctx.has_permission(SystemPermission.ITEMS_DELETE) is False

    def test_has_permission_with_module_permission_string(self):
        """has_permission() handles custom module permission strings via extra_permissions."""
        ctx = UserContextDTO(
            id=uuid.uuid4(),
            organization_id=None,
            role='user',
            permissions=set(),
            extra_permissions={'pos:sell', 'pos:refund'},
        )
        assert ctx.has_permission('pos:sell') is True
        assert ctx.has_permission('pos:void') is False

    def test_admin_role_bypasses_all_permission_checks(self):
        """role='admin' bypasses has_permission() for both system and module permissions."""
        ctx = UserContextDTO(
            id=uuid.uuid4(),
            organization_id=None,
            role='admin',
            permissions=set(),
            extra_permissions=set(),
        )
        assert ctx.has_permission(SystemPermission.SYSTEM_CONFIG_WRITE) is True
        assert ctx.has_permission('pos:void') is True

    def test_extra_permissions_defaults_to_empty_set(self):
        """extra_permissions field is optional and defaults to an empty set."""
        ctx = UserContextDTO(id=uuid.uuid4(), organization_id=None)
        assert ctx.extra_permissions == set()


# ── ModuleRegistry permission-definition tests ────────────────────────────


@pytest.mark.integration
class TestModuleRegistryPermissions:
    """Pure unit tests — no DB access needed."""

    def test_module_registry_register_and_retrieve_permissions(self):
        """Registered definitions surface as keys in get_all_permissions()."""
        mod_name = f'__test_rbac_{uuid.uuid4().hex[:8]}'
        module_registry.register_permission_defs(
            mod_name,
            [PermissionDef(key=k) for k in ('pos:sell', 'pos:refund', 'pos:void')],
        )
        try:
            all_perms = module_registry.get_all_permissions()
            assert 'pos:sell' in all_perms
            assert 'pos:refund' in all_perms
            assert 'pos:void' in all_perms
            # System permissions are still present
            assert 'items:read' in all_perms
            assert 'admin:access' in all_perms
        finally:
            module_registry._custom_permissions.pop(mod_name, None)

    def test_get_all_permissions_contains_all_system_permissions(self):
        """get_all_permissions() always includes every SystemPermission value."""
        all_perms = set(module_registry.get_all_permissions())
        for perm in SystemPermission:
            assert perm.value in all_perms, (
                f'{perm.value} missing from get_all_permissions()'
            )

    def test_get_all_permissions_is_deduplicated(self):
        """Registering the same string twice does not produce duplicates."""
        mod_name = f'__test_rbac_dup_{uuid.uuid4().hex[:8]}'
        module_registry.register_permission_defs(
            mod_name, [PermissionDef(key='items:read'), PermissionDef(key='items:read')]
        )
        try:
            all_perms = module_registry.get_all_permissions()
            assert all_perms.count('items:read') == 1
        finally:
            module_registry._custom_permissions.pop(mod_name, None)
