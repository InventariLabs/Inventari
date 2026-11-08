"""An invitation carries the role the inviter chose.

The join flow set ``user.role = 'user'`` outright, so an administrator
inviting a warehouse manager had to wait for them to arrive and then promote
them — while the API already accepted a ``role`` on the other invite endpoint,
the one no interface ever called.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.services.token_service import create_access_token, get_password_hash

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    await real_async_db_session.commit()
    return async_test_user


@pytest.fixture
async def outsider(real_async_db_session):
    from app.models.user import User

    user = User(
        email='outsider@example.com',
        hashed_password=get_password_hash('outsiderpass'),
        full_name='An Outsider',
        organization_id=None,
        role='user',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


async def _a_code_without_an_address(db, organization, admin) -> str:
    """A code as they were minted before every invitation named its address.

    The API no longer issues one, so the service writes it, the way such a
    code already sits in the database of an organization that upgrades.
    """
    from app.services._org_membership import create_invitation_code

    invitation = await create_invitation_code(db, organization.id, admin.id)
    await db.commit()
    return invitation['code']


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
class TestInvitationRole:
    async def test_the_chosen_role_reaches_the_account_that_joins(
        self, real_async_client, async_test_household, admin, outsider
    ):
        issued = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'manager', 'email': outsider.email},
            headers=_auth(admin),
        )
        assert issued.status_code == 200
        assert issued.json()['role'] == 'manager'

        joined = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': issued.json()['code']},
            headers=_auth(outsider),
        )
        assert joined.status_code == 200

        me = await real_async_client.get('/api/v1/auth/me', headers=_auth(outsider))
        assert me.json()['role'] == 'manager'

    async def test_opening_an_invitation_for_your_own_organization_demotes_nobody(
        self, real_async_client, async_test_household, admin
    ):
        """The link an administrator opens to look at it is their own role.

        Minting a `role=user` code for the organization you already administer
        and following it used to answer 200 and take `admin` away: the join
        wrote the invitation's role over the member's, and the guard that
        protects the last administrator only runs when the organization
        changes.
        """
        issued = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': admin.email},
            headers=_auth(admin),
        )
        assert issued.status_code == 200

        joined = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': issued.json()['code']},
            headers=_auth(admin),
        )
        assert joined.status_code == 200
        assert joined.json()['id'] == str(async_test_household.id)

        me = await real_async_client.get('/api/v1/auth/me', headers=_auth(admin))
        assert me.json()['role'] == 'admin'

    async def test_a_live_code_for_another_role_is_not_reused(
        self, real_async_client, async_test_household, admin
    ):
        # The endpoint hands back an existing unused code rather than issuing a
        # second one. Scoped by role, or the next arrival silently gets the
        # permissions of whoever was invited before them.
        first = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'viewer', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        second = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'manager', 'email': 'tomasz@example.com'},
            headers=_auth(admin),
        )

        assert first.json()['code'] != second.json()['code']
        assert second.json()['role'] == 'manager'

    async def test_each_invitation_gets_its_own_code(
        self, real_async_client, async_test_household, admin
    ):
        # The endpoint used to hand back a live code issued for the same role
        # rather than mint a second one. Once a code carries the address it
        # was meant for, that is a way to send one person another person's
        # invitation.
        first = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        second = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'tomasz@example.com'},
            headers=_auth(admin),
        )

        assert first.json()['code'] != second.json()['code']
        assert first.json()['invited_email'] == 'anna@example.com'
        assert second.json()['invited_email'] == 'tomasz@example.com'

    async def test_an_invitation_lives_a_week(
        self, real_async_client, async_test_household, admin
    ):
        # Fifteen minutes only ever suited a link handed over in person. A
        # code that has to survive a mailbox over a weekend needs days.
        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        expires_at = datetime.fromisoformat(response.json()['expires_at'])
        assert (
            timedelta(days=6, hours=23)
            < expires_at - datetime.now(UTC)
            <= timedelta(days=7)
        )

    async def test_an_unknown_role_is_refused(
        self, real_async_client, async_test_household, admin
    ):
        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'superuser', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'INVALID_ROLE'

    async def test_a_role_of_no_organization_is_refused_with_its_code(
        self, real_async_client, async_test_household, admin
    ):
        # The service refused with its key and the router replaced it with
        # VALIDATION_ERROR on the way out.
        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role_id': str(uuid4()), 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'ROLE_NOT_IN_ORGANIZATION'

    async def test_omitting_the_role_still_invites_a_member(
        self, real_async_client, async_test_household, admin
    ):
        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert response.status_code == 200
        assert response.json()['role'] == 'user'

    async def test_an_invitation_names_the_address_it_is_for(
        self, real_async_client, async_test_household, admin
    ):
        # The join holds a code to one address only when the code carries
        # one, so a code minted without an address admitted whoever held the
        # link. The screen always sent one; the API now asks for it too.
        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user'},
            headers=_auth(admin),
        )
        assert response.status_code == 422

        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert listed.json()['items'] == []


@pytest.mark.asyncio
class TestInvitationBinding:
    """A code opens only for the address it was issued for."""

    async def test_another_address_is_refused_and_the_code_survives(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
        outsider,
    ):
        issued = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        code = issued.json()['code']

        refused = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': code},
            headers=_auth(outsider),
        )
        # A live link opened by the wrong account says so (and the page offers
        # to sign out); it is not the 404 an expired or spent link answers.
        assert refused.status_code == 409
        assert refused.json()['detail']['code'] == 'INVITATION_OTHER_ADDRESS'
        assert 'anna@example.com' not in refused.text

        # Refusing must not burn the invitation — otherwise anyone holding a
        # leaked code could cancel it for the person it was meant for.
        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert listed.json()['items'][0]['is_used'] is False

    async def test_the_invited_address_joins_and_leaves_a_trace(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
        outsider,
    ):
        # The address is matched without regard to case: mail addresses are
        # handed over as they were typed, and the account was created from the
        # same string in whatever case its owner chose.
        issued = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'manager', 'email': 'OUTSIDER@Example.com'},
            headers=_auth(admin),
        )

        joined = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': issued.json()['code']},
            headers=_auth(outsider),
        )
        assert joined.status_code == 200

        from sqlalchemy import select

        from app.models.organization import OrganizationInvitation

        row = await real_async_db_session.scalar(
            select(OrganizationInvitation).where(
                OrganizationInvitation.code == issued.json()['code']
            )
        )
        assert row is not None
        assert row.is_used is True
        assert row.used_by_user_id == outsider.id
        assert row.used_at is not None

    async def test_a_code_issued_without_an_address_still_opens(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
        outsider,
    ):
        # Codes minted before invitations became personal keep working until
        # they expire, so deploying does not invalidate what is in flight.
        code = await _a_code_without_an_address(
            real_async_db_session, async_test_household, admin
        )

        joined = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': code},
            headers=_auth(outsider),
        )
        assert joined.status_code == 200


@pytest.mark.asyncio
class TestInvitationEmail:
    """The invitation goes out by mail when the organization has SMTP."""

    async def test_a_configured_organization_mails_the_invitation(
        self, real_async_client, async_test_household, admin, sent
    ):
        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'manager', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert response.status_code == 200
        assert response.json()['email_sent'] is True

        (message,) = sent
        assert message['to_email'] == 'anna@example.com'
        assert response.json()['code'] in message['join_link']
        assert message['role'] == 'manager'

    async def test_without_smtp_the_invitation_is_still_created(
        self, real_async_client, async_test_household, admin, monkeypatch
    ):
        from app.services.email_service import EmailService

        calls: list[object] = []

        async def _capture(*args, **kwargs):
            calls.append(args)
            return True

        monkeypatch.setattr(
            EmailService, 'send_invitation_async', staticmethod(_capture)
        )
        monkeypatch.setattr(
            EmailService, 'is_configured', staticmethod(lambda _=None: False)
        )

        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert response.status_code == 200
        assert response.json()['email_sent'] is False
        assert response.json()['code']
        assert calls == []

    async def test_a_failing_mail_server_does_not_undo_the_invitation(
        self, real_async_client, async_test_household, admin, monkeypatch
    ):
        # The code exists and works. Reporting a failure would have the
        # administrator issue a second invitation for the same person.
        from app.services.email_service import EmailService

        async def _explode(*args, **kwargs):
            raise OSError('mail server is on fire')

        monkeypatch.setattr(
            EmailService, 'send_invitation_async', staticmethod(_explode)
        )
        monkeypatch.setattr(
            EmailService, 'is_configured', staticmethod(lambda _=None: True)
        )

        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert response.status_code == 200
        assert response.json()['email_sent'] is False

        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert listed.json()['items'][0]['invited_email'] == 'anna@example.com'

    async def test_a_custom_role_travels_under_the_name_the_organization_gave_it(
        self, real_async_client, async_test_household, admin, sent
    ):
        role = await real_async_client.post(
            '/api/v1/roles', headers=_auth(admin), json={'name': 'Night Shift'}
        )
        await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role_id': role.json()['id'], 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        assert sent[0]['role'] == 'Night Shift'

    async def test_the_journal_names_the_custom_role_not_the_level_under_it(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
        sent,
    ):
        from sqlalchemy import select

        from app.models.audit_log import AuditLog

        role = await real_async_client.post(
            '/api/v1/roles', headers=_auth(admin), json={'name': 'Night Shift'}
        )
        await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role_id': role.json()['id'], 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        entry = await real_async_db_session.scalar(
            select(AuditLog).where(AuditLog.target_type == 'invitation')
        )
        assert entry.snapshot['role'] == 'Night Shift'


@pytest.mark.asyncio
class TestInvitationResend:
    """A pending invitation can be sent again, with its clock reset."""

    async def _issue(self, client, admin, sent_box=None, email='anna@example.com'):
        await client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': email},
            headers=_auth(admin),
        )
        listed = await client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        if sent_box is not None:
            sent_box.clear()
        return listed.json()['items'][0]

    async def test_resending_extends_the_deadline_and_keeps_the_code(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
        sent,
    ):
        entry = await self._issue(real_async_client, admin, sent)

        from sqlalchemy import select

        from app.models.organization import OrganizationInvitation

        row = await real_async_db_session.scalar(
            select(OrganizationInvitation).where(
                OrganizationInvitation.id == UUID(entry['id'])
            )
        )
        row.expires_at = datetime.now(UTC) + timedelta(days=1)
        await real_async_db_session.commit()

        response = await real_async_client.post(
            f'/api/v1/organizations/my/invitations/{entry["id"]}/resend',
            headers=_auth(admin),
        )
        assert response.status_code == 200
        assert response.json()['code'] == entry['code']
        assert response.json()['email_sent'] is True

        expires_at = datetime.fromisoformat(response.json()['expires_at'])
        assert expires_at - datetime.now(UTC) > timedelta(days=6)
        assert len(sent) == 1

    async def test_a_redeemed_invitation_refuses(
        self, real_async_client, async_test_household, admin, outsider, sent
    ):
        entry = await self._issue(real_async_client, admin, sent, email=outsider.email)
        joined = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': entry['code']},
            headers=_auth(outsider),
        )
        assert joined.status_code == 200

        response = await real_async_client.post(
            f'/api/v1/organizations/my/invitations/{entry["id"]}/resend',
            headers=_auth(admin),
        )
        assert response.status_code == 404

    async def test_a_withdrawn_invitation_refuses(
        self, real_async_client, async_test_household, admin, sent
    ):
        entry = await self._issue(real_async_client, admin, sent)
        await real_async_client.delete(
            f'/api/v1/organizations/my/invitations/{entry["id"]}',
            headers=_auth(admin),
        )

        response = await real_async_client.post(
            f'/api/v1/organizations/my/invitations/{entry["id"]}/resend',
            headers=_auth(admin),
        )
        assert response.status_code == 404

    async def test_without_smtp_the_endpoint_says_so(
        self, real_async_client, async_test_household, admin, sent, monkeypatch
    ):
        # Silently succeeding would leave the administrator waiting for a
        # message that was never going to be sent.
        entry = await self._issue(real_async_client, admin, sent)

        from app.services.email_service import EmailService

        monkeypatch.setattr(
            EmailService, 'is_configured', staticmethod(lambda _=None: False)
        )

        response = await real_async_client.post(
            f'/api/v1/organizations/my/invitations/{entry["id"]}/resend',
            headers=_auth(admin),
        )
        assert response.status_code == 400
        assert sent == []


@pytest.mark.asyncio
class TestInvitationRegistration:
    """The registration path honours the same invitation rules as joining.

    An invitation code is the one thing that lets somebody create an account
    here without an operator approving it — the administrator's approval was
    given in advance, when they issued the invitation. That makes the code the
    approval, and every rule the join flow puts on it has to hold on this path
    too.
    """

    async def _issue(self, client, admin, email, expect=200):
        response = await client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': email},
            headers=_auth(admin),
        )
        assert response.status_code == expect
        return response.json()

    async def test_registering_under_another_address_is_refused(
        self, real_async_client, async_test_household, admin
    ):
        # Otherwise the address binding guards only the account that already
        # exists, and a leaked link still buys a brand-new one.
        issued = await self._issue(real_async_client, admin, 'anna@example.com')

        response = await real_async_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'stranger@example.com',
                'password': 'Password123',
                'full_name': 'A Stranger',
                'invite_code': issued['code'],
            },
        )
        assert response.status_code == 400

    async def test_the_invited_address_registers_without_an_operator(
        self, real_async_client, real_async_db_session, async_test_household, admin
    ):
        issued = await self._issue(real_async_client, admin, 'anna@example.com')

        response = await real_async_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'Anna@Example.com',
                'password': 'Password123',
                'full_name': 'Anna Kowalska',
                'invite_code': issued['code'],
            },
        )
        assert response.status_code == 201

        from sqlalchemy import select

        from app.models.user import User

        registered = await real_async_db_session.scalar(
            select(User).where(User.id == UUID(response.json()['id']))
        )
        assert registered is not None
        assert registered.organization_id == async_test_household.id
        assert registered.is_active is True

    async def test_a_withdrawn_invitation_registers_nobody(
        self, real_async_client, async_test_household, admin
    ):
        await self._issue(real_async_client, admin, 'anna@example.com')
        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        entry = listed.json()['items'][0]
        await real_async_client.delete(
            f'/api/v1/organizations/my/invitations/{entry["id"]}',
            headers=_auth(admin),
        )

        response = await real_async_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'anna@example.com',
                'password': 'Password123',
                'full_name': 'Anna Kowalska',
                'invite_code': entry['code'],
            },
        )
        assert response.status_code == 400

    async def test_a_code_issued_without_an_address_still_registers(
        self, real_async_client, real_async_db_session, async_test_household, admin
    ):
        code = await _a_code_without_an_address(
            real_async_db_session, async_test_household, admin
        )

        response = await real_async_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'anna@example.com',
                'password': 'Password123',
                'full_name': 'Anna Kowalska',
                'invite_code': code,
            },
        )
        assert response.status_code == 201


@pytest.mark.asyncio
class TestInvitationRevoke:
    """An administrator can take an invitation back."""

    async def test_a_revoked_code_no_longer_opens(
        self, real_async_client, async_test_household, admin, outsider
    ):
        issued = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'outsider@example.com'},
            headers=_auth(admin),
        )
        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        invitation_id = listed.json()['items'][0]['id']

        revoked = await real_async_client.delete(
            f'/api/v1/organizations/my/invitations/{invitation_id}',
            headers=_auth(admin),
        )
        assert revoked.status_code == 204

        refused = await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': issued.json()['code']},
            headers=_auth(outsider),
        )
        assert refused.status_code == 404

    async def test_a_revoked_invitation_leaves_the_list(
        self, real_async_client, async_test_household, admin
    ):
        await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        invitation_id = listed.json()['items'][0]['id']

        await real_async_client.delete(
            f'/api/v1/organizations/my/invitations/{invitation_id}',
            headers=_auth(admin),
        )

        after = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert after.json()['items'] == []

    async def test_another_organizations_invitation_is_not_found(
        self, real_async_client, real_async_db_session, async_test_household, admin
    ):
        from app.models.organization import Organization, OrganizationInvitation

        other_org = Organization(name='Other Org', created_by=admin.id)
        real_async_db_session.add(other_org)
        await real_async_db_session.flush()
        stranger = OrganizationInvitation(
            organization_id=other_org.id,
            code='STRANGER',
            created_by=admin.id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        real_async_db_session.add(stranger)
        await real_async_db_session.commit()

        response = await real_async_client.delete(
            f'/api/v1/organizations/my/invitations/{stranger.id}',
            headers=_auth(admin),
        )
        assert response.status_code == 404

    async def test_the_revocation_names_who_did_it(
        self, real_async_client, real_async_db_session, async_test_household, admin
    ):
        # The row drops off the list, so the audit entry is the only place the
        # withdrawal survives.
        await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin),
        )
        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        invitation_id = listed.json()['items'][0]['id']

        await real_async_client.delete(
            f'/api/v1/organizations/my/invitations/{invitation_id}',
            headers=_auth(admin),
        )

        from sqlalchemy import select

        from app.models.audit_log import AuditLog

        entry = await real_async_db_session.scalar(
            select(AuditLog)
            .where(AuditLog.target_type == 'invitation')
            .order_by(AuditLog.created_at.desc())
        )
        assert entry is not None
        assert entry.action == 'SOFT_DELETE'
        assert entry.user_id == admin.id
        assert entry.snapshot['invited_email'] == 'anna@example.com'
        # The code itself never goes in — an audit entry a reader can use to
        # join is not an audit entry.
        assert 'code' not in entry.snapshot


@pytest.mark.asyncio
class TestInvitationList:
    async def test_an_issued_invitation_stays_visible(
        self, real_async_client, async_test_household, admin, outsider
    ):
        # Fifteen minutes and no list: whether anyone had used the link could
        # only be inferred from who turned up among the members.
        issued = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'viewer', 'email': outsider.email},
            headers=_auth(admin),
        )

        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert listed.status_code == 200
        (entry,) = listed.json()['items']
        assert entry['code'] == issued.json()['code']
        assert entry['role'] == 'viewer'
        assert entry['is_used'] is False

        await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': issued.json()['code']},
            headers=_auth(outsider),
        )

        after = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert after.json()['items'][0]['is_used'] is True

    async def test_the_list_names_the_recipient_and_the_redemption(
        self, real_async_client, async_test_household, admin, outsider
    ):
        await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'outsider@example.com'},
            headers=_auth(admin),
        )
        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        (entry,) = listed.json()['items']
        assert entry['invited_email'] == 'outsider@example.com'
        assert entry['used_by_user_id'] is None
        assert entry['used_at'] is None

        await real_async_client.post(
            '/api/v1/organizations/join',
            json={'code': entry['code']},
            headers=_auth(outsider),
        )

        after = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert after.json()['items'][0]['used_by_user_id'] == str(outsider.id)
        assert after.json()['items'][0]['used_at'] is not None

    async def test_long_dead_invitations_stop_piling_up(
        self, real_async_client, real_async_db_session, async_test_household, admin
    ):
        # Sixteen rows, thirteen of them corpses, was the screen. Nothing ever
        # removed one, so the list grew for the life of the installation.
        from app.models.organization import OrganizationInvitation

        now = datetime.now(UTC)
        recent = OrganizationInvitation(
            organization_id=async_test_household.id,
            code='RECENT12',
            created_by=admin.id,
            expires_at=now - timedelta(days=30),
        )
        ancient = OrganizationInvitation(
            organization_id=async_test_household.id,
            code='ANCIENT1',
            created_by=admin.id,
            expires_at=now - timedelta(days=100),
        )
        real_async_db_session.add_all([recent, ancient])
        await real_async_db_session.commit()

        listed = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        codes = {entry['code'] for entry in listed.json()['items']}
        assert 'RECENT12' in codes
        assert 'ANCIENT1' not in codes

        again = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert {entry['code'] for entry in again.json()['items']} == {'RECENT12'}

    async def test_a_member_cannot_read_the_codes(
        self, real_async_client, real_async_db_session, async_test_household, admin
    ):
        from app.models.user import User

        member = User(
            email='plain_member@example.com',
            hashed_password=get_password_hash('memberpass'),
            full_name='Plain Member',
            organization_id=async_test_household.id,
            role='user',
            is_active=True,
        )
        real_async_db_session.add(member)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(member)
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestInvitationDelivery:
    """An invitation whose mail was lost does not look like one waiting to be opened.

    Both read "not used yet" on a list that knows only whether the code was
    redeemed, and the two ask opposite things of an administrator: send it
    another way, or leave it alone.
    """

    async def _queue_row(self, db, organization_id, to_email, status):
        from app.models.email_job import EmailJob

        job = EmailJob(
            organization_id=organization_id,
            to_email=to_email,
            subject='You have been invited',
            html_content='<p>join us</p>',
            status=status,
            attempts=5 if status == 'failed' else 1,
            last_error='[Errno 111] Connection refused' if status == 'failed' else None,
        )
        db.add(job)
        await db.commit()
        return job

    async def _invite(self, client, admin, email):
        response = await client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=_auth(admin),
            json={'role': 'user', 'email': email},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def _listing(self, client, admin) -> dict[str, str | None]:
        response = await client.get(
            '/api/v1/organizations/my/invitations', headers=_auth(admin)
        )
        assert response.status_code == 200, response.text
        return {
            row['invited_email']: row['email_status']
            for row in response.json()['items']
        }

    async def test_the_list_separates_a_lost_mail_from_a_delivered_one(
        self, real_async_client, real_async_db_session, admin, sent
    ):
        await self._invite(real_async_client, admin, 'lost@example.com')
        await self._invite(real_async_client, admin, 'arrived@example.com')
        org_id = admin.organization_id
        await self._queue_row(
            real_async_db_session, org_id, 'lost@example.com', 'failed'
        )
        await self._queue_row(
            real_async_db_session, org_id, 'arrived@example.com', 'sent'
        )

        states = await self._listing(real_async_client, admin)

        assert states['lost@example.com'] == 'failed'
        assert states['arrived@example.com'] == 'sent'

    async def test_an_invitation_with_no_mail_behind_it_claims_nothing(
        self, real_async_client, real_async_db_session, admin, sent
    ):
        """An installation without SMTP is a supported installation.

        Reporting those as failures would flag every invitation in it, and
        the administrator handing the link over themselves did nothing
        wrong.
        """
        await self._invite(real_async_client, admin, 'byhand@example.com')

        states = await self._listing(real_async_client, admin)

        assert states['byhand@example.com'] is None

    async def test_mail_older_than_the_invitation_is_not_read_as_its_own(
        self, real_async_client, real_async_db_session, admin, sent
    ):
        """A second invitation to the same address starts with a clean slate.

        The first one's failure belongs to the first one; showing it under a
        code minted afterwards would report a message that was never sent.
        """
        await self._queue_row(
            real_async_db_session, admin.organization_id, 'again@example.com', 'failed'
        )
        await self._invite(real_async_client, admin, 'again@example.com')

        states = await self._listing(real_async_client, admin)

        assert states['again@example.com'] is None
