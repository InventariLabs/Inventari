"""HTTP endpoint tests for /api/v1/roles.

Roles router exposes org-scoped role listing + mutation:
- GET    /roles                  -- list org roles (admin only)
- POST   /roles                  -- create role        (admin only)
- PUT    /roles/{id}/permissions -- replace permission set on a role
- POST   /roles/users/{uid}/{rid} -- link a user to a role

Reads funnel through CoreAPI (core_api.roles), writes go through
the service helpers. Admin-only access is enforced by
``require_permission(SYSTEM_CONFIG_WRITE)``; non-admin requests
return HTTP 403.
"""

from __future__ import annotations

import pytest

from app.core._registry_class import module_registry
from app.core.contracts import SystemPermission
from app.core.module_manifest_schema import PermissionDef
from app.core.testing import ModuleTestHelper
from app.models.role import Role, UserRole
from app.services import permissions_service
from app.services.builtin_roles import builtin_role_permissions
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _make_admin(db, user_id, org_id):
    """Promote a user to admin so the router guard lets the request through."""
    from app.models.user import User

    user = await db.get(User, user_id)
    user.role = 'admin'
    await db.flush()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
class TestRolesRouter:
    async def test_unauthenticated_request_returns_401(
        self,
        real_async_client,
    ):
        """No JWT header means auth middleware blocks before permission check."""
        response = await real_async_client.get('/api/v1/roles')
        assert response.status_code == 401

    async def test_list_roles_returns_org_roles(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        # Seed a role so the list is non-empty
        role = await permissions_service.create_role_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            name='Manager',
            permissions=[SystemPermission.ITEMS_READ.value],
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        assert response.status_code == 200
        body = response.json()['items']
        assert any(r['name'] == 'Manager' for r in body)
        assert any(r['id'] == str(role.id) for r in body)

    async def test_the_catalogue_names_a_switched_off_module_when_asked_for_all(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """History reads a permission whatever its module's state is today.

        The roles matrix leaves a module the organization does not run out; the
        audit log, naming the permissions of a key issued while it was on,
        asks for every module.
        """
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        saved = dict(module_registry._custom_permissions)
        module_registry.register_permission_defs(
            'dormant', [PermissionDef(key='dormant:write')]
        )
        try:
            default = await real_async_client.get(
                '/api/v1/roles/permission-catalog', headers=_auth(async_test_user)
            )
            whole = await real_async_client.get(
                '/api/v1/roles/permission-catalog',
                params={'all_modules': 'true'},
                headers=_auth(async_test_user),
            )
        finally:
            module_registry._custom_permissions.clear()
            module_registry._custom_permissions.update(saved)

        assert default.status_code == whole.status_code == 200
        # `dormant` is a module this organization does not run.
        assert 'dormant' not in {g['module'] for g in default.json()['modules']}
        assert 'dormant' in {g['module'] for g in whole.json()['modules']}

    async def test_the_catalogue_is_read_by_whoever_may_read_the_audit_log(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """The journal names a key's permissions from this list.

        A member whose custom role holds only ``admin:access`` reads the
        journal, so the labels it needs must not wait for the stronger
        ``system:config:write``; a member holding neither still gets 403.
        """

        async def member_with(*grants: str):
            user = await ModuleTestHelper.create_user_async(
                real_async_db_session,
                async_test_household,
                email=f'member-{len(grants)}-{grants[0].replace(":", "-")}@example.com',
                role='user',
            )
            role = Role(
                name=f'custom_{grants[0]}',
                permissions=list(grants),
                is_system=False,
                organization_id=async_test_household.id,
            )
            real_async_db_session.add(role)
            await real_async_db_session.flush()
            real_async_db_session.add(UserRole(user_id=user.id, role_id=role.id))
            await real_async_db_session.commit()
            return user

        reader = await member_with('admin:access')
        outsider = await member_with('items:read')

        allowed = await real_async_client.get(
            '/api/v1/roles/permission-catalog',
            params={'all_modules': 'true'},
            headers=_auth(reader),
        )
        refused = await real_async_client.get(
            '/api/v1/roles/permission-catalog',
            params={'all_modules': 'true'},
            headers=_auth(outsider),
        )

        assert allowed.status_code == 200, allowed.text
        assert refused.status_code == 403

    async def test_create_role_persists_with_initial_permissions(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/roles',
            json={
                'name': 'Custom Role',
                'permissions': [
                    SystemPermission.ITEMS_WRITE.value,
                    SystemPermission.STORAGES_READ.value,
                ],
            },
            headers=_auth(async_test_user),
        )
        assert response.status_code == 201
        body = response.json()
        assert body['name'] == 'Custom Role'
        assert set(body['permissions']) == {
            SystemPermission.ITEMS_WRITE.value,
            SystemPermission.STORAGES_READ.value,
        }

    async def test_update_permissions_replaces_existing_set(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        role = await permissions_service.create_role_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            name='Auditor',
            permissions=[SystemPermission.ITEMS_READ.value],
        )
        await real_async_db_session.commit()

        response = await real_async_client.put(
            f'/api/v1/roles/{role.id}/permissions',
            json={
                'permissions': [
                    SystemPermission.ITEMS_READ.value,
                    SystemPermission.ORG_READ.value,
                ],
            },
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body['permissions']) == {
            SystemPermission.ITEMS_READ.value,
            SystemPermission.ORG_READ.value,
        }

    async def test_assign_role_links_user(
        self,
        real_async_client,
        real_async_db_session,
        db_session,
        async_test_household,
        async_test_user,
    ):
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        role = await permissions_service.create_role_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            name='Auditor',
            permissions=[SystemPermission.ITEMS_READ.value],
        )
        await real_async_db_session.commit()

        # Create a target user via the SYNC db_session so the row commits
        # before the HTTP request's separate session tries to read it.
        from uuid import uuid4

        from app.models.user import User
        from app.services.auth_service import get_password_hash

        target_user_id = uuid4()
        target_user = User(
            id=target_user_id,
            email=f'target-{uuid4().hex[:6]}@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='Target User',
            organization_id=async_test_household.id,
            role='user',
            is_active=True,
        )
        db_session.add(target_user)
        db_session.commit()

        response = await real_async_client.post(
            f'/api/v1/roles/users/{target_user_id}/{role.id}',
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200

        roles = await permissions_service.list_roles_for_user_async(
            real_async_db_session,
            async_test_household.id,
            target_user_id,
        )
        assert any(r.id == role.id for r in roles)


@pytest.mark.asyncio
class TestRoleLifecycle:
    """Renaming and deleting a custom role — the half the API used to lack.

    A role could be created and its permissions edited, and then neither
    renamed nor removed. The delete is deliberately the strict kind: the
    association rows cascade, so a permissive one would succeed silently and
    drop each holder back to the level their ``User.role`` names. For a role
    that *narrows* access that is a promotion, and nothing afterwards would
    show it happened.
    """

    async def _admin(self, db, user, org):
        await _make_admin(db, user.id, org.id)
        await db.commit()

    async def _role(self, db, org, name='Warehouse operator'):
        role = await permissions_service.create_role_async(
            db,
            organization_id=org.id,
            name=name,
            permissions=[SystemPermission.ITEMS_READ.value],
        )
        await db.commit()
        return role

    async def test_rename_changes_the_name_and_keeps_the_permissions(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await self._admin(real_async_db_session, async_test_user, async_test_household)
        role = await self._role(real_async_db_session, async_test_household)

        response = await real_async_client.patch(
            f'/api/v1/roles/{role.id}',
            json={'name': 'Stock keeper'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['name'] == 'Stock keeper'
        assert body['permissions'] == [SystemPermission.ITEMS_READ.value]

    async def test_rename_onto_an_existing_name_is_refused(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await self._admin(real_async_db_session, async_test_user, async_test_household)
        await self._role(real_async_db_session, async_test_household, name='Taken')
        role = await self._role(
            real_async_db_session, async_test_household, name='Other'
        )

        response = await real_async_client.patch(
            f'/api/v1/roles/{role.id}',
            json={'name': 'taken'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == 400, response.text
        # Keyed refusal: the envelope carries the sentence and its language.
        assert 'already exists' in response.json()['detail']['message']

    async def test_a_duplicate_name_is_refused_in_the_readers_language(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """The clash is a keyed refusal: Polish request, Polish sentence,
        and the envelope names the language the text is actually in."""
        await self._admin(real_async_db_session, async_test_user, async_test_household)
        await self._role(
            real_async_db_session, async_test_household, name='Stock keeper'
        )

        response = await real_async_client.post(
            '/api/v1/roles',
            json={
                'name': 'stock keeper',
                'permissions': [SystemPermission.ITEMS_READ.value],
            },
            headers={**_auth(async_test_user), 'Accept-Language': 'pl'},
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['lang'] == 'pl'
        assert 'Rola o nazwie "stock keeper" już istnieje' in detail['message']
        assert 'already exists' not in detail['message']

    async def test_delete_removes_a_role_nobody_holds(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await self._admin(real_async_db_session, async_test_user, async_test_household)
        role = await self._role(real_async_db_session, async_test_household)

        response = await real_async_client.delete(
            f'/api/v1/roles/{role.id}', headers=_auth(async_test_user)
        )
        assert response.status_code == 204, response.text

        listing = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        assert all(r['id'] != str(role.id) for r in listing.json()['items'])

    async def test_delete_is_refused_while_somebody_holds_the_role(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await self._admin(real_async_db_session, async_test_user, async_test_household)
        role = await self._role(real_async_db_session, async_test_household)
        await permissions_service.assign_role_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            role_id=role.id,
            actor_user_id=async_test_user.id,
        )
        await real_async_db_session.commit()

        response = await real_async_client.delete(
            f'/api/v1/roles/{role.id}', headers=_auth(async_test_user)
        )

        assert response.status_code == 409, response.text
        assert response.json()['detail']['code'] == 'ROLE_IN_USE'
        assert response.json()['detail']['member_count'] == 1

        # And it is still there — a refusal that deleted anyway would be worse
        # than no refusal at all.
        listing = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        assert any(r['id'] == str(role.id) for r in listing.json()['items'])

    async def test_the_list_says_how_many_people_hold_each_role(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """So a refusal is visible before anybody clicks delete."""
        await self._admin(real_async_db_session, async_test_user, async_test_household)
        held = await self._role(real_async_db_session, async_test_household, 'Held')
        free = await self._role(real_async_db_session, async_test_household, 'Free')
        await permissions_service.assign_role_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            role_id=held.id,
            actor_user_id=async_test_user.id,
        )
        await real_async_db_session.commit()

        body = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        counts = {r['id']: r['member_count'] for r in body.json()['items']}
        assert counts[str(held.id)] == 1
        assert counts[str(free.id)] == 0

    async def test_members_endpoint_names_who_stands_in_the_way(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await self._admin(real_async_db_session, async_test_user, async_test_household)
        role = await self._role(real_async_db_session, async_test_household)
        await permissions_service.assign_role_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            role_id=role.id,
            actor_user_id=async_test_user.id,
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            f'/api/v1/roles/{role.id}/members', headers=_auth(async_test_user)
        )

        assert response.status_code == 200, response.text
        assert [m['email'] for m in response.json()['items']] == [async_test_user.email]

    async def test_another_organisations_role_refuses_both(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """A role belongs to one organisation, and this is not it.

        This case used to be written about a role belonging to *no*
        organisation, which the roles list showed to every tenant and the
        permission check honoured in every tenant. There is no such row any
        more; what is left to refuse is somebody else's.
        """
        from app.models.organization import Organization

        await self._admin(real_async_db_session, async_test_user, async_test_household)
        elsewhere = Organization(name='Somebody Else', currency='PLN')
        real_async_db_session.add(elsewhere)
        await real_async_db_session.flush()
        theirs = Role(organization_id=elsewhere.id, name='Support', is_system=False)
        real_async_db_session.add(theirs)
        await real_async_db_session.commit()

        assert (
            await real_async_client.patch(
                f'/api/v1/roles/{theirs.id}',
                json={'name': 'Nope'},
                headers=_auth(async_test_user),
            )
        ).status_code == 400
        assert (
            await real_async_client.delete(
                f'/api/v1/roles/{theirs.id}', headers=_auth(async_test_user)
            )
        ).status_code == 400


@pytest.mark.asyncio
class TestBuiltInRolesAreListed:
    """The four levels every account actually holds, on the screen about roles.

    `/settings/roles` promised "what each role in this organisation may do"
    and answered only for custom roles: admin, manager, user and viewer are
    not rows in `roles` — they live on `User.role` and their permissions are
    computed — so a listing built from the table left out the levels every
    account in a fresh organisation carries. The screen's own empty state
    admitted they exist ("Built-in levels cover most cases"), and the
    read-only path in its editor had been written and never reached.
    """

    async def test_the_four_levels_are_listed_read_only(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )

        assert response.status_code == 200
        body = response.json()['items']
        builtin = {r['name']: r for r in body if r['is_system']}
        assert set(builtin) == {'admin', 'manager', 'user', 'viewer'}
        assert all(r['organization_id'] is None for r in builtin.values())
        # And nothing else: a fresh organisation has no roles of its own, and
        # the two rows an archived RBAC migration seeded without an
        # organisation used to appear here as a second "Administrator" and a
        # second "User", in every tenant of the installation.
        assert [r['name'] for r in body] == ['admin', 'manager', 'user', 'viewer']

    async def test_a_built_in_level_carries_the_permissions_it_grants(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """The row and the guard read the same function, so they cannot drift.

        This is the whole point of the screen: an administrator asking "what
        can a viewer actually do" gets the set that decides the answer, not a
        description of it written somewhere else.
        """
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        viewer = next(
            r
            for r in response.json()['items']
            if r['is_system'] and r['name'] == 'viewer'
        )

        assert set(viewer['permissions']) == builtin_role_permissions('viewer')
        assert SystemPermission.ITEMS_READ.value in viewer['permissions']
        assert SystemPermission.ITEMS_WRITE.value not in viewer['permissions']

    async def test_an_admin_row_shows_the_whole_catalogue(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        # `has_permission` returns True for an admin whatever the set says, so
        # a shorter list on the screen would describe an account the API does
        # not enforce.
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        admin = next(
            r
            for r in response.json()['items']
            if r['is_system'] and r['name'] == 'admin'
        )

        assert set(admin['permissions']) == set(module_registry.get_all_permissions())

    async def test_built_in_ids_are_the_same_on_every_request(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        # Derived from the level's name rather than stored. A React key and a
        # query cache need that much.
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        first = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        second = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )

        ids = {r['name']: r['id'] for r in first.json()['items'] if r['is_system']}
        assert ids == {
            r['name']: r['id'] for r in second.json()['items'] if r['is_system']
        }

    async def test_a_built_in_level_cannot_be_edited_through_its_id(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Read-only means the id opens nothing, not just that a button is hidden."""
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        listing = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        viewer_id = next(
            r['id']
            for r in listing.json()['items']
            if r['is_system'] and r['name'] == 'viewer'
        )

        response = await real_async_client.put(
            f'/api/v1/roles/{viewer_id}/permissions',
            json={'permissions': [SystemPermission.ITEMS_WRITE.value]},
            headers=_auth(async_test_user),
        )

        # 400, not 404: the router maps "role not found" to a bad request for
        # every unknown id, which is its existing shape and not this
        # listing's to change. What matters here is that a derived id is not
        # a handle on anything.
        assert response.status_code == 400

    async def test_the_count_says_how_many_people_hold_the_level(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await _make_admin(
            real_async_db_session, async_test_user.id, async_test_household.id
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/roles', headers=_auth(async_test_user)
        )
        admin = next(
            r
            for r in response.json()['items']
            if r['is_system'] and r['name'] == 'admin'
        )

        assert admin['member_count'] >= 1
