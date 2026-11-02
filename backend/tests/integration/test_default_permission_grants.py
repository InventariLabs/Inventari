"""Enabling a module grants its declared default permissions.

Without this the first enforced module permission would be admin-only in
practice: nobody holds ``approvals:approve`` until somebody ticks a box, so a
freshly enabled module looks broken to every manager in the organization.

What the grant deliberately does *not* do is create roles. Inventing an
org-wide role as a side effect of switching a module on would be a surprising
grant of authority, so a `default_roles` name with no matching role simply
grants nothing.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core._registry_class import module_registry
from app.core.module_manifest_schema import PermissionDef
from app.models.organization import Organization
from app.models.role import Role
from app.services.module_lifecycle_service import grant_default_permissions


class _FakeModule:
    """Stand-in for a BaseModule — only ``metadata.permissions`` is read."""

    def __init__(self, permissions: list[PermissionDef]) -> None:
        self.metadata = type(
            'Meta', (), {'name': 'warranty', 'permissions': permissions}
        )()


async def _make_org(real_async_db_session) -> Organization:
    org = Organization(name=f'Grant Org {uuid.uuid4().hex[:6]}', currency='PLN')
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


async def _make_role(real_async_db_session, org: Organization, name: str) -> Role:
    role = Role(name=name, permissions=[], is_system=False, organization_id=org.id)
    real_async_db_session.add(role)
    await real_async_db_session.flush()
    return role


async def _reload(real_async_db_session, role: Role) -> list[str]:
    await real_async_db_session.refresh(role)
    return list(role.permissions or [])


@pytest.mark.integration
@pytest.mark.asyncio
class TestDefaultPermissionGrants:
    async def test_a_matching_role_receives_the_permission(
        self, real_async_db_session
    ) -> None:
        org = await _make_org(real_async_db_session)
        role = await _make_role(real_async_db_session, org, 'manager')
        module = _FakeModule(
            [PermissionDef(key='warranty:write', default_roles=['manager'])]
        )

        await grant_default_permissions(module, str(org.id), real_async_db_session)

        assert 'warranty:write' in await _reload(real_async_db_session, role)

    async def test_a_role_with_another_name_is_untouched(
        self, real_async_db_session
    ) -> None:
        org = await _make_org(real_async_db_session)
        viewer = await _make_role(real_async_db_session, org, 'viewer')
        module = _FakeModule(
            [PermissionDef(key='warranty:write', default_roles=['manager'])]
        )

        await grant_default_permissions(module, str(org.id), real_async_db_session)

        assert await _reload(real_async_db_session, viewer) == []

    async def test_no_role_is_created_when_none_matches(
        self, real_async_db_session
    ) -> None:
        org = await _make_org(real_async_db_session)
        module = _FakeModule(
            [PermissionDef(key='warranty:write', default_roles=['manager'])]
        )

        await grant_default_permissions(module, str(org.id), real_async_db_session)

        result = await real_async_db_session.execute(
            select(Role).where(Role.organization_id == org.id)
        )
        assert result.scalars().all() == []

    async def test_enabling_twice_does_not_duplicate(
        self, real_async_db_session
    ) -> None:
        org = await _make_org(real_async_db_session)
        role = await _make_role(real_async_db_session, org, 'manager')
        module = _FakeModule(
            [PermissionDef(key='warranty:write', default_roles=['manager'])]
        )

        await grant_default_permissions(module, str(org.id), real_async_db_session)
        await grant_default_permissions(module, str(org.id), real_async_db_session)

        assert (await _reload(real_async_db_session, role)).count('warranty:write') == 1

    async def test_existing_permissions_survive(self, real_async_db_session) -> None:
        org = await _make_org(real_async_db_session)
        role = await _make_role(real_async_db_session, org, 'manager')
        role.permissions = ['items:read']
        await real_async_db_session.flush()
        module = _FakeModule(
            [PermissionDef(key='warranty:write', default_roles=['manager'])]
        )

        await grant_default_permissions(module, str(org.id), real_async_db_session)

        assert set(await _reload(real_async_db_session, role)) == {
            'items:read',
            'warranty:write',
        }

    async def test_a_permission_without_default_roles_grants_nothing(
        self, real_async_db_session
    ) -> None:
        org = await _make_org(real_async_db_session)
        role = await _make_role(real_async_db_session, org, 'manager')
        module = _FakeModule([PermissionDef(key='warranty:read')])

        await grant_default_permissions(module, str(org.id), real_async_db_session)

        assert await _reload(real_async_db_session, role) == []

    async def test_a_role_in_another_org_is_not_touched(
        self, real_async_db_session
    ) -> None:
        org = await _make_org(real_async_db_session)
        other = await _make_org(real_async_db_session)
        foreign = await _make_role(real_async_db_session, other, 'manager')
        module = _FakeModule(
            [PermissionDef(key='warranty:write', default_roles=['manager'])]
        )

        await grant_default_permissions(module, str(org.id), real_async_db_session)

        assert await _reload(real_async_db_session, foreign) == []


@pytest.mark.unit
class TestApprovalsShipsDefaults:
    def test_the_approve_permission_names_a_default_role(self) -> None:
        """The first enforced module permission must reach somebody by default."""
        module_registry.discover_modules()
        catalog = module_registry.get_permissions_catalog(['approvals'])

        (section,) = [m for m in catalog['modules'] if m['module'] == 'approvals']
        approve = next(
            p for p in section['permissions'] if p['key'] == 'approvals:approve'
        )
        assert approve['default_roles'] == ['manager']
