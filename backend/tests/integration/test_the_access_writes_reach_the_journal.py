"""The access writes that make and unmake memberships leave a journal entry.

Creating an organization, seeding its first locations, joining it, leaving
it, switching between organizations and sending an invitation again are
administrative acts an operator opens the journal to answer for. Each one
now rides the transaction of the write it describes, so the entry and the
change stand or fall together.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.organization import Organization, OrganizationInvitation
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _make_user(email: str, organization_id, role: str = 'user', **kwargs) -> User:
    return User(
        email=email,
        hashed_password=get_password_hash('testpassword123'),
        full_name='Journal Subject',
        organization_id=organization_id,
        role=role,
        is_active=True,
        **kwargs,
    )


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    """The org and its admin, committed — the HTTP client uses its own session."""
    await real_async_db_session.commit()
    return async_test_user


async def _entries(client, user, **params) -> list[dict]:
    response = await client.get('/api/v1/audit-log', headers=_auth(user), params=params)
    assert response.status_code == 200
    return response.json()['items']


@pytest.fixture
def sent(monkeypatch):
    """Capture invitation mail instead of sending it, with SMTP pretending to
    be configured."""
    from app.services.email_service import EmailService

    captured: list[dict] = []

    async def _capture(to_email, join_link, **kwargs):
        captured.append({'to_email': to_email, 'join_link': join_link, **kwargs})
        return True

    monkeypatch.setattr(EmailService, 'send_invitation_async', staticmethod(_capture))
    monkeypatch.setattr(
        EmailService, 'is_configured', staticmethod(lambda _=None: True)
    )
    return captured


@pytest.mark.asyncio
class TestTheAccessWritesAreRecorded:
    async def test_creating_an_organization_is_recorded(
        self,
        real_async_client,
        real_async_db_session,
    ):
        founder = _make_user('founder@example.com', None)
        real_async_db_session.add(founder)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(founder)

        response = await real_async_client.post(
            '/api/v1/organizations',
            json={'name': 'Fundacja', 'currency': 'PLN'},
            headers=_auth(founder),
        )
        assert response.status_code == 201

        entries = await _entries(real_async_client, founder, target_type='organization')
        assert len(entries) == 1
        entry = entries[0]
        assert entry['action'] == 'CREATE'
        assert entry['target_id'] == response.json()['id']
        assert entry['snapshot']['name'] == 'Fundacja'
        assert entry['user_email'] == founder.email

    async def test_the_default_locations_are_recorded(
        self,
        real_async_client,
        async_test_household,
        admin,
    ):
        response = await real_async_client.post(
            '/api/v1/organizations/current/defaults',
            headers=_auth(admin),
        )
        assert response.status_code == 200
        created = response.json()
        assert created, 'the profile declares at least one starting location'

        entries = await _entries(real_async_client, admin, target_type='storage')
        assert len(entries) == len(created)
        assert {entry['snapshot']['name'] for entry in entries} == {
            location['name'] for location in created
        }
        assert all(entry['action'] == 'CREATE' for entry in entries)
        assert all(entry['snapshot']['usage'] for entry in entries)
        assert all(entry['user_email'] == admin.email for entry in entries)

    async def test_joining_an_organization_is_recorded(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
    ):
        joiner = _make_user('joiner@example.com', None)
        real_async_db_session.add(joiner)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(joiner)

        invitation = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'email': joiner.email},
            headers=_auth(admin),
        )
        assert invitation.status_code == 200

        response = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': invitation.json()['code']},
            headers=_auth(joiner),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='org_member')
        assert len(entries) == 1
        assert entries[0]['action'] == 'CREATE'
        assert entries[0]['target_id'] == str(joiner.id)
        assert entries[0]['snapshot']['name'] == joiner.email
        assert entries[0]['user_email'] == joiner.email

    async def test_switching_organizations_journals_both_memberships(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
    ):
        switcher = _make_user('switcher@example.com', async_test_household.id)
        real_async_db_session.add(switcher)
        await real_async_db_session.flush()

        second = Organization(name='Second Organization', enabled_modules=[])
        real_async_db_session.add(second)
        await real_async_db_session.flush()
        real_async_db_session.add(
            OrganizationInvitation(
                organization_id=second.id,
                code='SWITCHME',
                created_by=admin.id,
                expires_at=datetime.now(UTC) + timedelta(days=7),
                role='admin',
                invited_email=switcher.email,
            )
        )
        await real_async_db_session.commit()
        await real_async_db_session.refresh(switcher)

        response = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': 'SWITCHME'},
            headers=_auth(switcher),
        )
        assert response.status_code == 200

        left = await _entries(real_async_client, admin, target_type='org_member')
        assert len(left) == 1
        assert left[0]['action'] == 'SOFT_DELETE'
        assert left[0]['target_id'] == str(switcher.id)
        assert left[0]['snapshot']['name'] == switcher.email

        joined = await _entries(real_async_client, switcher, target_type='org_member')
        assert len(joined) == 1
        assert joined[0]['action'] == 'CREATE'
        assert joined[0]['target_id'] == str(switcher.id)

    async def test_leaving_an_organization_is_recorded(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
    ):
        member = _make_user('leaver@example.com', async_test_household.id)
        real_async_db_session.add(member)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(member)

        response = await real_async_client.post(
            '/api/v1/organizations/my/leave',
            headers=_auth(member),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='org_member')
        assert len(entries) == 1
        assert entries[0]['action'] == 'SOFT_DELETE'
        assert entries[0]['target_id'] == str(member.id)
        assert entries[0]['snapshot']['name'] == member.email
        assert entries[0]['user_email'] == member.email

    async def test_an_invitation_entry_points_at_the_invitation_not_the_organization(
        self,
        real_async_client,
        async_test_household,
        admin,
        sent,
    ):
        """Creating and redeeming an invitation shared the organization's id.

        A row whose target is the organization's own id cannot be told from
        any other, and cannot be tied to the invitation it records.
        """
        created = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert created.status_code == 200
        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        invitation_id = listed.json()['items'][0]['id']

        entries = await _entries(real_async_client, admin, target_type='invitation')

        (creation,) = [entry for entry in entries if entry['action'] == 'CREATE']
        assert creation['target_id'] == invitation_id
        assert creation['target_id'] != str(async_test_household.id)
        assert creation['snapshot']['invited_email'] == 'anna@example.com'

    async def test_resending_an_invitation_is_recorded(
        self,
        real_async_client,
        async_test_household,
        admin,
        sent,
    ):
        created = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert created.status_code == 200
        code = created.json()['code']

        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations',
            headers=_auth(admin),
        )
        assert listed.status_code == 200
        invitation_id = listed.json()['items'][0]['id']

        response = await real_async_client.post(
            f'/api/v1/organizations/my/invitations/{invitation_id}/resend',
            headers=_auth(admin),
        )
        assert response.status_code == 200
        assert response.json()['email_sent'] is True

        entries = await _entries(real_async_client, admin, target_type='invitation')
        updates = [entry for entry in entries if entry['action'] == 'UPDATE']
        assert len(updates) == 1
        update = updates[0]
        assert update['target_id'] == invitation_id
        assert update['snapshot']['invited_email'] == 'anna@example.com'
        assert (
            update['snapshot']['before']['expires_at']
            != update['snapshot']['after']['expires_at']
        )
        assert update['user_email'] == admin.email
        # An audit entry a reader can use to join is not an audit entry.
        assert code not in str(entries)


@pytest.mark.asyncio
class TestSuperuserAccessChangesAreRecorded:
    async def test_blocking_unblocking_and_deactivating_are_recorded(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
    ):
        superuser = _make_user(
            'root@example.com',
            async_test_household.id,
            role='admin',
            is_superuser=True,
        )
        member = _make_user('member@example.com', async_test_household.id)
        real_async_db_session.add_all([superuser, member])
        await real_async_db_session.commit()
        await real_async_db_session.refresh(superuser)
        await real_async_db_session.refresh(member)

        blocked = await real_async_client.post(
            f'/api/v1/users/{member.id}/block',
            json={'reason': 'spam'},
            headers=_auth(superuser),
        )
        assert blocked.status_code == 200
        assert blocked.json()['is_blocked'] is True

        unblocked = await real_async_client.post(
            f'/api/v1/users/{member.id}/unblock',
            headers=_auth(superuser),
        )
        assert unblocked.status_code == 200
        assert unblocked.json()['is_blocked'] is False

        # A second unblock changes nothing and must not write a second entry.
        again = await real_async_client.post(
            f'/api/v1/users/{member.id}/unblock',
            headers=_auth(superuser),
        )
        assert again.status_code == 200

        deactivated = await real_async_client.post(
            f'/api/v1/users/{member.id}/activate',
            headers=_auth(superuser),
        )
        assert deactivated.status_code == 200
        assert deactivated.json()['is_active'] is False

        entries = await _entries(real_async_client, superuser, target_type='org_member')
        assert all(entry['target_id'] == str(member.id) for entry in entries)
        assert all(entry['snapshot']['name'] == member.email for entry in entries)
        assert all(entry['user_email'] == superuser.email for entry in entries)
        blocks = [entry for entry in entries if entry['reason'] == 'spam']
        assert len(blocks) == 1
        assert blocks[0]['snapshot']['after'] == {'is_blocked': True}
        transitions = [
            (entry['snapshot']['before'], entry['snapshot']['after'])
            for entry in entries
        ]
        assert ({'is_blocked': False}, {'is_blocked': True}) in transitions
        assert ({'is_active': True}, {'is_active': False}) in transitions
        unblocks = [
            transition
            for transition in transitions
            if transition == ({'is_blocked': True}, {'is_blocked': False})
        ]
        assert len(unblocks) == 1, 'the no-op unblock should not be recorded'
        assert len(entries) == 3
