"""Acts on the role catalogue are journalled, with the actor.

`docs/subsystems/ROLES.md` decides not to cap role creation at the creator's
own permissions, and rests that decision on one sentence: a self-promotion
leaves a record even though nothing refuses it. The record was a `logger.info`
on stdout — the organization's journal had `CREATE invitation`, `UPDATE
organization` and `UPDATE module` from the same minute, and nothing about a
role. These tests are what makes that sentence true.
"""

from __future__ import annotations

import pytest

from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _entries(client, user, **params) -> list[dict]:
    response = await client.get('/api/v1/audit-log', headers=_auth(user), params=params)
    assert response.status_code == 200
    return response.json()['items']


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    """The org and its admin, committed — the HTTP client uses its own session."""
    await real_async_db_session.commit()
    return async_test_user


async def _create_role(client, admin, *, name: str, permissions: list[str]) -> dict:
    response = await client.post(
        '/api/v1/roles',
        json={'name': name, 'permissions': permissions},
        headers=_auth(admin),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
class TestTheRoleCatalogueIsJournalled:
    async def test_creating_a_role_names_it_and_its_permissions(
        self, real_async_client, admin
    ):
        role = await _create_role(
            real_async_client,
            admin,
            name='Shift lead',
            permissions=['items:read', 'items:write'],
        )

        entries = await _entries(real_async_client, admin, target_type='role')
        entry = next(e for e in entries if e['action'] == 'CREATE')
        assert entry['target_id'] == role['id']
        assert entry['snapshot']['name'] == 'Shift lead'
        assert entry['snapshot']['permissions'] == ['items:read', 'items:write']
        assert entry['user_email'] == admin.email

    async def test_a_permission_change_carries_both_sets(
        self, real_async_client, admin
    ):
        role = await _create_role(
            real_async_client, admin, name='Counter', permissions=['items:read']
        )

        changed = await real_async_client.put(
            f'/api/v1/roles/{role["id"]}/permissions',
            json={'permissions': ['items:read', 'admin:access']},
            headers=_auth(admin),
        )
        assert changed.status_code == 200, changed.text

        entries = await _entries(real_async_client, admin, target_type='role')
        entry = next(e for e in entries if e['action'] == 'UPDATE')
        assert entry['snapshot']['before']['permissions'] == ['items:read']
        assert entry['snapshot']['after']['permissions'] == [
            'items:read',
            'admin:access',
        ]
        assert entry['user_email'] == admin.email

    async def test_a_rename_carries_both_names(self, real_async_client, admin):
        role = await _create_role(
            real_async_client, admin, name='Old name', permissions=[]
        )

        renamed = await real_async_client.patch(
            f'/api/v1/roles/{role["id"]}',
            json={'name': 'New name'},
            headers=_auth(admin),
        )
        assert renamed.status_code == 200, renamed.text

        entries = await _entries(real_async_client, admin, target_type='role')
        entry = next(e for e in entries if e['action'] == 'UPDATE')
        assert entry['snapshot']['before']['name'] == 'Old name'
        assert entry['snapshot']['after']['name'] == 'New name'

    async def test_a_deleted_role_survives_in_the_entry_that_names_it(
        self, real_async_client, admin
    ):
        role = await _create_role(
            real_async_client, admin, name='Temporary', permissions=['items:read']
        )

        deleted = await real_async_client.delete(
            f'/api/v1/roles/{role["id"]}', headers=_auth(admin)
        )
        assert deleted.status_code == 204, deleted.text

        entries = await _entries(real_async_client, admin, target_type='role')
        entry = next(e for e in entries if e['action'] == 'HARD_DELETE')
        assert entry['target_id'] == role['id']
        assert entry['snapshot']['name'] == 'Temporary'
        assert entry['snapshot']['permissions'] == ['items:read']


@pytest.mark.asyncio
class TestASelfPromotionLeavesARecord:
    async def test_assigning_a_role_says_who_got_it_and_who_gave_it(
        self, real_async_client, admin
    ):
        role = await _create_role(
            real_async_client,
            admin,
            name='Administrators',
            permissions=['admin:access'],
        )

        assigned = await real_async_client.post(
            f'/api/v1/roles/users/{admin.id}/{role["id"]}',
            headers=_auth(admin),
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()['created'] is True

        entries = await _entries(real_async_client, admin, target_type='org_member')
        entry = next(e for e in entries if e['target_id'] == str(admin.id))
        assert entry['snapshot']['name'] == admin.email
        assert entry['snapshot']['role_name'] == 'Administrators'
        assert entry['snapshot']['permissions'] == ['admin:access']
        assert entry['user_email'] == admin.email

    async def test_an_assignment_that_changes_nothing_writes_nothing(
        self, real_async_client, admin
    ):
        role = await _create_role(
            real_async_client, admin, name='Again', permissions=['items:read']
        )
        for _ in range(2):
            response = await real_async_client.post(
                f'/api/v1/roles/users/{admin.id}/{role["id"]}',
                headers=_auth(admin),
            )
            assert response.status_code == 200, response.text

        entries = await _entries(real_async_client, admin, target_type='org_member')
        assert len([e for e in entries if e['target_id'] == str(admin.id)]) == 1


@pytest.mark.asyncio
class TestTheSideTheMemberLandedOnIsNamed:
    """The side the member landed on names the role it points at.

    ``before`` carried the pair the reader knows (``role_id`` with
    ``role_name``, see ``docs/subsystems/AUDIT.md``); ``after`` carried the id
    alone, so the entry read `Rola własna: Magazynier REV1941 → a0f03448` —
    the name appeared only when the role's own entry happened to share the
    page. A role is deletable and the journal is opened months later, so the
    name is written with the entry on both sides.
    """

    @pytest.fixture
    async def admin_and_member(
        self, real_async_db_session, async_test_user, async_test_user2
    ):
        """The admin and a second member, committed — the client has its own
        session."""
        await real_async_db_session.commit()
        return async_test_user, async_test_user2

    async def test_assigning_a_custom_role_writes_its_name_beside_its_id(
        self, real_async_client, admin_and_member
    ):
        admin, member = admin_and_member
        role = await _create_role(
            real_async_client,
            admin,
            name='Magazynier REV1941',
            permissions=['items:read'],
        )

        assigned = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{member.id}/role',
            json={'role_id': role['id']},
            headers=_auth(admin),
        )
        assert assigned.status_code == 200, assigned.text

        entries = await _entries(real_async_client, admin, target_type='org_member')
        entry = next(e for e in entries if e['target_id'] == str(member.id))
        assert entry['snapshot']['after']['role_id'] == role['id']
        assert entry['snapshot']['after']['role_name'] == 'Magazynier REV1941'
        # The level stays beside it, and the side the member came from held no
        # custom role to name.
        assert entry['snapshot']['after']['role'] == 'user'
        assert 'role_name' not in entry['snapshot']['before']


@pytest.mark.asyncio
class TestTakingACustomRoleAwayIsJournalled:
    """The role a member loses has to be named in the entry that records it.

    A custom role is taken away either way the member endpoint can be called,
    because the service drops the member's links on both paths: picking a
    built-in level, and picking another custom role. Both entries used to
    forget it. Picking a level sent ``{'role': 'user'}``, so both sides of the
    snapshot carried the same built-in level and nothing else, and the entry
    read as no change at all — the Detail column showed ``—`` and the role
    that actually went away was named nowhere in the journal. Swapping one
    custom role for another sent ``{'role_id': …}``, and the held role was
    read only on the other path, so that entry said the member had held no
    custom role.
    """

    @pytest.fixture
    async def admin_and_member(
        self, real_async_db_session, async_test_user, async_test_user2
    ):
        """The admin and a second member, committed — the client has its own
        session."""
        await real_async_db_session.commit()
        return async_test_user, async_test_user2

    async def test_removing_a_custom_role_names_the_role_it_removed(
        self, real_async_client, admin_and_member
    ):
        admin, member = admin_and_member
        role = await _create_role(
            real_async_client,
            admin,
            name='Magazynier',
            permissions=['items:read'],
        )
        assigned = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{member.id}/role',
            json={'role_id': role['id']},
            headers=_auth(admin),
        )
        assert assigned.status_code == 200, assigned.text

        removed = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{member.id}/role',
            json={'role': 'user'},
            headers=_auth(admin),
        )
        assert removed.status_code == 200, removed.text

        entries = await _entries(real_async_client, admin, target_type='org_member')
        entry = next(
            e
            for e in entries
            if e['target_id'] == str(member.id)
            and e['snapshot'].get('before', {}).get('role_name') == 'Magazynier'
        )
        assert entry['snapshot']['before']['role_id'] == role['id']
        # And the side that is now empty promises nothing: the entry says the
        # member holds no custom role, so it cannot be read as a keep.
        assert entry['snapshot']['after'] == {'role': 'user'}
        assert entry['user_email'] == admin.email

    async def test_swapping_one_custom_role_for_another_names_the_one_it_removed(
        self, real_async_client, admin_and_member
    ):
        """The replacement is chosen from the same dropdown, so the request
        carries ``role_id`` and nothing else — there is no built-in level in
        it to hang the read on. Built from the level alone, the entry says the
        member held no custom role, and the one that was dropped goes
        unnamed."""
        admin, member = admin_and_member
        held = await _create_role(
            real_async_client,
            admin,
            name='Magazynier',
            permissions=['items:read'],
        )
        replacement = await _create_role(
            real_async_client,
            admin,
            name='Kucharz',
            permissions=['items:read'],
        )
        assigned = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{member.id}/role',
            json={'role_id': held['id']},
            headers=_auth(admin),
        )
        assert assigned.status_code == 200, assigned.text

        swapped = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{member.id}/role',
            json={'role_id': replacement['id']},
            headers=_auth(admin),
        )
        assert swapped.status_code == 200, swapped.text

        entries = await _entries(real_async_client, admin, target_type='org_member')
        entry = next(
            e
            for e in entries
            if e['target_id'] == str(member.id)
            and e['snapshot'].get('after', {}).get('role_id') == replacement['id']
        )
        # The level the member keeps is the same on both sides, which is why
        # the removed role has to be named here.
        assert entry['snapshot']['before']['role'] == 'user'
        assert entry['snapshot']['after']['role'] == 'user'
        assert entry['snapshot']['before']['role_id'] == held['id']
        assert entry['snapshot']['before']['role_name'] == 'Magazynier'
        assert entry['user_email'] == admin.email

    async def test_a_built_in_role_change_keeps_its_historical_shape(
        self, real_async_client, admin_and_member
    ):
        """A member who held no custom role is journalled exactly as before:
        the built-in path writes ``{'role': …}`` on both sides and nothing
        else. This is what a snapshot read months ago still reads as."""
        admin, member = admin_and_member
        changed = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{member.id}/role',
            json={'role': 'manager'},
            headers=_auth(admin),
        )
        assert changed.status_code == 200, changed.text

        entries = await _entries(real_async_client, admin, target_type='org_member')
        entry = next(e for e in entries if e['target_id'] == str(member.id))
        assert entry['snapshot']['before'] == {'role': 'user'}
        assert entry['snapshot']['after'] == {'role': 'manager'}
