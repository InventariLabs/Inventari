"""Administrative acts leave a trace.

``log_action_*`` was called by items, documents, purchase orders, approvals
and maker — and by nothing else. After a session that created a storage
location, three webhooks and two API keys, revoked a key, enabled three
modules, changed the organization's settings, generated an invitation and
posted a global announcement, the audit log held **one** entry: the creation
of a product.

That is the gap closes, and these are the acts it covers. The API key
half lives with its module (``app/modules/api_keys/tests``), since calling
those endpoints needs the module enabled.
"""

from __future__ import annotations

import pytest

from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    """The org and its admin, committed — the HTTP client uses its own session."""
    await real_async_db_session.commit()
    return async_test_user


async def _entries(client, user, **params) -> list[dict]:
    response = await client.get('/api/v1/audit-log', headers=_auth(user), params=params)
    assert response.status_code == 200
    return response.json()['items']


@pytest.mark.asyncio
class TestAdministrativeActionsAreRecorded:
    async def test_changing_organization_settings_names_what_changed(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        # "Permanent deletion" saved on click, said nothing, and left no trace
        # anywhere — so an irreversible capability could be switched on with
        # no record that anyone had done it.
        response = await real_async_client.put(
            '/api/v1/organizations',
            json={'settings': {'allow_permanent_delete': True}},
            headers=_auth(admin),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='organization')
        assert len(entries) == 1
        assert entries[0]['action'] == 'UPDATE'
        assert entries[0]['snapshot']['after'] == {'allow_permanent_delete': True}
        assert entries[0]['user_email'] == admin.email

    async def test_the_issuer_data_printed_on_documents_is_recorded(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        # The tax ID and the address are what every printed document says the
        # organization is. Saving them left the journal empty, while the
        # smaller settings beside them wrote a row.
        response = await real_async_client.put(
            '/api/v1/organizations',
            json={
                'tax_id': 'PL1234567890',
                'country': 'PL',
                'address': {'street': 'Main 1', 'city': 'Warsaw'},
            },
            headers=_auth(admin),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='organization')
        assert len(entries) == 1
        after = entries[0]['snapshot']['after']
        assert after['tax_id'] == 'PL1234567890'
        assert after['country'] == 'PL'
        assert after['address'] == 'Main 1, Warsaw'

        # Saving the same block again moves nothing, so it writes nothing.
        again = await real_async_client.put(
            '/api/v1/organizations',
            json={
                'tax_id': 'PL1234567890',
                'country': 'PL',
                'address': {'street': 'Main 1', 'city': 'Warsaw'},
            },
            headers=_auth(admin),
        )
        assert again.status_code == 200
        assert (
            len(await _entries(real_async_client, admin, target_type='organization'))
            == 1
        )

    async def test_an_unchanged_save_writes_nothing(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        # A log that records "someone pressed Save" for every no-op buries the
        # entries that mean something.
        response = await real_async_client.put(
            '/api/v1/organizations',
            json={'name': async_test_household.name},
            headers=_auth(admin),
        )
        assert response.status_code == 200

        assert (
            await _entries(real_async_client, admin, target_type='organization') == []
        )

    async def test_a_secret_records_that_it_changed_not_what_to(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        response = await real_async_client.put(
            '/api/v1/organizations',
            json={
                'settings': {
                    'smtp': {
                        'host': 'smtp.example.com',
                        'port': 587,
                        'username': 'postmaster',
                        'password': 'hunter2',
                        'from_email': 'noreply@example.com',
                    }
                }
            },
            headers=_auth(admin),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='organization')
        assert entries, 'the SMTP change should be recorded'
        assert 'hunter2' not in str(entries[0]['snapshot'])

    async def test_generating_an_invitation_is_recorded_without_the_code(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=_auth(admin),
        )
        assert response.status_code == 200
        code = response.json()['code']

        entries = await _entries(real_async_client, admin, target_type='invitation')
        assert len(entries) == 1
        assert entries[0]['action'] == 'CREATE'
        # An audit entry a reader can use to join is not an audit entry.
        assert code not in str(entries[0]['snapshot'])

    async def test_changing_a_members_role_records_both_sides(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
    ):
        from app.models.user import User
        from app.services.token_service import get_password_hash

        member = User(
            email='member@example.com',
            hashed_password=get_password_hash('memberpass'),
            full_name='A Member',
            organization_id=async_test_household.id,
            role='user',
            is_active=True,
        )
        real_async_db_session.add(member)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(member)

        response = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{member.id}/role',
            json={'role': 'manager'},
            headers=_auth(admin),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='org_member')
        assert len(entries) == 1
        assert entries[0]['snapshot']['before'] == {'role': 'user'}
        assert entries[0]['snapshot']['after'] == {'role': 'manager'}
        assert entries[0]['target_id'] == str(member.id)

    async def test_switching_a_module_on_is_recorded(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
    ):
        # The household starts with every module on, and a toggle that
        # changes nothing is not an act the journal records. Switch recipes
        # off first so this is a real switch.
        async_test_household.enabled_modules = [
            name
            for name in (async_test_household.enabled_modules or [])
            if name != 'recipes'
        ]
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/modules/toggle',
            json={'module_name': 'recipes', 'enabled': True},
            headers=_auth(admin),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='module')
        assert len(entries) == 1
        assert entries[0]['snapshot']['name'] == 'recipes'
        assert entries[0]['snapshot']['after'] == {'enabled': True}

    async def test_a_no_op_module_switch_writes_nothing(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        # The household already has recipes on; switching it on again
        # changes nothing, and a journal that records keystrokes buries the
        # entries that mean something.
        response = await real_async_client.post(
            '/api/v1/modules/toggle',
            json={'module_name': 'recipes', 'enabled': True},
            headers=_auth(admin),
        )
        assert response.status_code == 200

        assert await _entries(real_async_client, admin, target_type='module') == []


@pytest.mark.asyncio
class TestAuditLogFilters:
    async def test_target_types_come_from_the_log_not_a_fixed_list(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        # The filter offered three values typed by hand, two of them from
        # modules this profile does not install, while the things that really
        # changed were not on it at all.
        empty = await real_async_client.get(
            '/api/v1/audit-log/target-types', headers=_auth(admin)
        )
        assert empty.status_code == 200
        assert empty.json() == []

        await real_async_client.put(
            '/api/v1/organizations',
            json={'settings': {'allow_permanent_delete': True}},
            headers=_auth(admin),
        )

        after = await real_async_client.get(
            '/api/v1/audit-log/target-types', headers=_auth(admin)
        )
        assert after.json() == ['organization']

    async def test_the_range_has_an_upper_bound(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
    ):
        # `since` alone can only answer "everything after"; a range needs both
        # ends to answer "what happened that afternoon".
        from datetime import UTC, datetime, timedelta
        from uuid import uuid4

        from app.models.audit_log import AuditAction, AuditLog

        now = datetime.now(UTC)
        old = AuditLog(
            organization_id=async_test_household.id,
            user_id=admin.id,
            action=AuditAction.CREATE.value,
            target_type='item',
            target_id=uuid4(),
            created_at=now - timedelta(days=10),
        )
        real_async_db_session.add(old)
        await real_async_db_session.commit()

        cutoff = (now - timedelta(days=5)).isoformat()
        within = await _entries(real_async_client, admin, until=cutoff)
        assert len(within) == 1

        after_cutoff = await _entries(real_async_client, admin, since=cutoff)
        assert after_cutoff == []
