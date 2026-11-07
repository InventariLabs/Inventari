"""The public invitation check behind the /join screen.

A dead join link must be answerable before anyone is sent anywhere: the
signed-out visitor the link reached asks `/public/invitation/{code}` and the
refusal is what puts "invalid or expired, ask for a new one" on the screen —
instead of a silent redirect to /login.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status

pytestmark = pytest.mark.integration


def _seed_invitation(
    db_session,
    code: str,
    *,
    expires_in: timedelta = timedelta(days=7),
    is_used: bool = False,
    revoked: bool = False,
    invited_email: str | None = None,
):
    from app.models.organization import Organization, OrganizationInvitation
    from app.models.user import User
    from app.services.token_service import get_password_hash

    org = Organization(name=f'Invite Check Org {uuid.uuid4().hex[:8]}')
    db_session.add(org)
    db_session.flush()
    admin = User(
        email=f'inviter_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        organization_id=org.id,
        full_name='Ada Inviter',
        role='admin',
        is_active=True,
    )
    db_session.add(admin)
    db_session.flush()
    invitation = OrganizationInvitation(
        organization_id=org.id,
        code=code,
        created_by=admin.id,
        expires_at=datetime.now(UTC) + expires_in,
        is_used=is_used,
        invited_email=invited_email,
    )
    if revoked:
        invitation.revoked_at = datetime.now(UTC)
    db_session.add(invitation)
    db_session.commit()
    return invitation


class TestPublicInvitationCheck:
    def test_live_code_answers_valid_without_an_account(self, client, db_session):
        invitation = _seed_invitation(db_session, 'LIVECODE1')

        response = client.get(f'/public/invitation/{invitation.code}')

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['valid'] is True
        assert body['organization_name'].startswith('Invite Check Org')
        assert body['inviter_name'] == 'Ada Inviter'
        assert body['role'] == 'user'
        assert body['invited_email'] is None

    def test_names_the_address_the_invitation_is_for(self, client, db_session):
        invitation = _seed_invitation(
            db_session, 'BOUNDCO1', invited_email='nowa@example.com'
        )

        response = client.get(f'/public/invitation/{invitation.code}')

        assert response.json()['invited_email'] == 'nowa@example.com'

    @pytest.mark.parametrize(
        'seed',
        [
            pytest.param({'invited_email': 'nowa@example.com'}, id='wrong-address'),
            pytest.param(
                {'expires_in': timedelta(days=-1)},
                id='expired',
            ),
            pytest.param({'is_used': True}, id='used'),
            pytest.param({'revoked': True}, id='withdrawn'),
        ],
    )
    def test_every_refusal_is_one_sentence_that_names_the_likely_fix(
        self, client, db_session, seed
    ):
        # A prober must not tell the four dead ends apart, so the answer is the
        # same status and the same words for all of them; and the words name
        # what the reader can do about it — the address or a fresh invitation.
        invitation = _seed_invitation(db_session, 'REFUSED01', **seed)

        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'zla@example.com',
                'password': 'Str0ng-passw0rd!',
                'invite_code': invitation.code,
            },
        )
        unknown = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'zla@example.com',
                'password': 'Str0ng-passw0rd!',
                'invite_code': 'NOBODY999',
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert response.json() == unknown.json()
        message = response.json()['detail']['message']
        assert 'address' in message
        assert 'new one' in message

    def test_unknown_code_refuses_with_404(self, client):
        response = client.get('/public/invitation/NOBODY999')

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_expired_code_refuses_with_404(self, client, db_session):
        invitation = _seed_invitation(
            db_session, 'OLDCODE1', expires_in=timedelta(days=-1)
        )

        response = client.get(f'/public/invitation/{invitation.code}')

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_spent_code_refuses_with_404(self, client, db_session):
        invitation = _seed_invitation(db_session, 'SPENTCO1', is_used=True)

        response = client.get(f'/public/invitation/{invitation.code}')

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_withdrawn_code_refuses_with_404(self, client, db_session):
        invitation = _seed_invitation(db_session, 'GONECODE', revoked=True)

        response = client.get(f'/public/invitation/{invitation.code}')

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_refusal_keeps_its_code_and_gives_no_registration_advice(self, client):
        response = client.get('/public/invitation/NOBODY999')

        detail = response.json()['detail']
        assert detail['code'] == 'ORGANIZATION_INVITE_INVALID'
        assert 'address' not in detail['message']
        assert 'register' not in detail['message']
