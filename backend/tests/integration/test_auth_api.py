"""
Integration tests for authorization API endpoints.

Tests verify correctness of endpoints:
- POST /api/v1/auth/register - user registration
- POST /api/v1/auth/login - user login
- POST /api/v1/auth/refresh - token refresh
- POST /api/v1/auth/logout - logout
- GET /api/v1/auth/me - get user profile
"""

import time
from datetime import UTC, datetime

import jwt as pyjwt
import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.config import settings


@pytest.mark.integration
class TestAuthRegister:
    """Tests for registration endpoint."""

    def test_register_success(self, client):
        """Tests successful user registration."""
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'newuser@example.com',
                'password': 'Password123',
                'full_name': 'New User',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['email'] == 'newuser@example.com'
        assert data['full_name'] == 'New User'
        assert 'id' in data
        assert 'hashed_password' not in data
        assert 'created_at' in data

    def test_register_inherits_the_language_the_request_arrived_in(self, client):
        """A Polish browser got a Polish sign-in screen and English onboarding.

        The schema defaulted `preferred_language` to 'en', so an account
        created without an explicit choice was an English account, and the
        reader had to find the picker to get their own language back.
        """
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'polish@example.com',
                'password': 'Password123',
                'full_name': 'Polska Przeglądarka',
            },
            headers={'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.8'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['preferred_language'] == 'pl'

    def test_register_keeps_an_explicit_choice_over_the_header(self, client):
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'chose-german@example.com',
                'password': 'Password123',
                'preferred_language': 'de',
            },
            headers={'Accept-Language': 'pl-PL,pl;q=0.9'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['preferred_language'] == 'de'

    def test_register_answers_the_same_for_known_and_unknown_address(
        self, client, test_user
    ):
        """no oracle on a seeded installation.

        Direct registration is refused once an installation has users and the
        caller holds no invite. That refusal has to look identical whether or
        not the address already has an account, otherwise anyone can walk a
        list of addresses and learn who is here.
        """
        taken = client.post(
            '/api/v1/auth/register',
            json={
                'email': test_user.email,
                'password': 'Password123',
                'full_name': 'Duplicate User',
            },
        )
        unknown = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'nobody-here@example.com',
                'password': 'Password123',
                'full_name': 'Stranger',
            },
        )

        assert taken.status_code == unknown.status_code, taken.text
        assert taken.json() == unknown.json()

    def test_register_refused_without_invite_once_seeded(self, client, test_user):
        """`/register` is bootstrap-or-invite, not open self-service.

        The UI only ever posts here for the first account or with an invite
        code in the URL; the endpoint used to accept a bare email/password
        from anyone and mint an account plus a fresh organization.
        """
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'uninvited@example.com',
                'password': 'Password123',
                'full_name': 'Uninvited',
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            client.post(
                '/api/v1/auth/login',
                data={'username': 'uninvited@example.com', 'password': 'Password123'},
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )

    def test_register_with_valid_invite_still_works(
        self, client, db_session, test_user, test_household
    ):
        """The gate must not close the door on an invited user."""
        from datetime import UTC, datetime, timedelta

        from app.models.organization import OrganizationInvitation

        invitation = OrganizationInvitation(
            organization_id=test_household.id,
            code='ABCD2345',
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            created_by=test_user.id,
        )
        db_session.add(invitation)
        db_session.commit()

        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'invited@example.com',
                'password': 'Password123',
                'full_name': 'Invited User',
                'invite_code': 'ABCD2345',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        login = client.post(
            '/api/v1/auth/login',
            data={'username': 'invited@example.com', 'password': 'Password123'},
        )
        assert login.status_code == status.HTTP_200_OK, login.text

    def test_register_with_invite_receives_the_invitations_role(
        self, client, db_session, test_user, test_household
    ):
        """An invite minted for a manager must land a manager, not a 'user'."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.models.organization import OrganizationInvitation
        from app.models.user import User

        db_session.add(
            OrganizationInvitation(
                organization_id=test_household.id,
                code='MGR23456',
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                created_by=test_user.id,
                role='manager',
            )
        )
        db_session.commit()

        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'invited-manager@example.com',
                'password': 'Password123',
                'full_name': 'Invited Manager',
                'invite_code': 'MGR23456',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        user = db_session.scalar(
            select(User).where(User.email == 'invited-manager@example.com')
        )
        assert user is not None
        assert user.role == 'manager'
        assert user.organization_id == test_household.id

    def test_register_with_invite_receives_custom_role(
        self, client, db_session, test_user, test_household
    ):
        """A custom role on the invite ends up linked to the new account."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.models.organization import OrganizationInvitation
        from app.models.role import Role, UserRole
        from app.models.user import User

        role = Role(
            organization_id=test_household.id,
            name='Warehousekeeper',
            permissions=['items:read'],
            is_system=False,
        )
        db_session.add(role)
        db_session.flush()
        db_session.add(
            OrganizationInvitation(
                organization_id=test_household.id,
                code='CUST2345',
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                created_by=test_user.id,
                role_id=role.id,
            )
        )
        db_session.commit()

        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'invited-custom@example.com',
                'password': 'Password123',
                'full_name': 'Invited Custom',
                'invite_code': 'CUST2345',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        user = db_session.scalar(
            select(User).where(User.email == 'invited-custom@example.com')
        )
        assert user is not None
        link = db_session.scalar(
            select(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            )
        )
        assert link is not None

    def test_register_with_invite_burns_the_code(
        self, client, db_session, test_user, test_household
    ):
        """One code admits exactly one account — a second registration with
        the same code must be refused."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.models.organization import OrganizationInvitation
        from app.models.user import User

        invitation = OrganizationInvitation(
            organization_id=test_household.id,
            code='ONCE2345',
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            created_by=test_user.id,
        )
        db_session.add(invitation)
        db_session.commit()

        payload = {
            'password': 'Password123',
            'full_name': 'First',
            'invite_code': 'ONCE2345',
        }
        first = client.post(
            '/api/v1/auth/register',
            json={**payload, 'email': 'first@example.com'},
        )
        assert first.status_code == status.HTTP_201_CREATED, first.text

        db_session.refresh(invitation)
        assert invitation.is_used is True

        second = client.post(
            '/api/v1/auth/register',
            json={**payload, 'email': 'second@example.com'},
        )
        assert second.status_code == status.HTTP_400_BAD_REQUEST, second.text
        assert (
            db_session.scalar(select(User).where(User.email == 'second@example.com'))
            is None
        )

    def test_used_invite_code_is_no_longer_valid(
        self, client, db_session, test_user, test_household
    ):
        """The validation probe agrees: a burned code reports invalid."""
        from datetime import timedelta

        from app.models.organization import OrganizationInvitation

        db_session.add(
            OrganizationInvitation(
                organization_id=test_household.id,
                code='USED2345',
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                created_by=test_user.id,
                is_used=True,
            )
        )
        db_session.commit()

        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'late@example.com',
                'password': 'Password123',
                'full_name': 'Too Late',
                'invite_code': 'USED2345',
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    def test_register_invalid_email(self, client):
        """Tests registration with invalid email."""
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'invalid-email',
                'password': 'Password123',
                'full_name': 'Test User',
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_missing_email(self, client):
        """Tests registration without email."""
        response = client.post(
            '/api/v1/auth/register',
            json={'password': 'Password123', 'full_name': 'Test User'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_missing_password(self, client):
        """Tests registration without password."""
        response = client.post(
            '/api/v1/auth/register',
            json={'email': 'test@example.com', 'full_name': 'Test User'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_without_full_name(self, client):
        """Tests registration without name (optional field)."""
        response = client.post(
            '/api/v1/auth/register',
            json={'email': 'minimal@example.com', 'password': 'Password123'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['email'] == 'minimal@example.com'
        assert data['full_name'] is None


@pytest.mark.integration
class TestAuthLogin:
    """Tests for login endpoint."""

    def test_login_success(self, client, test_user):
        """Tests successful login."""
        response = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'access_token' in data
        assert data['token_type'] == 'bearer'
        assert len(data['access_token']) > 0

    def test_login_keeps_the_refresh_token_out_of_the_body(self, client, test_user):
        """the refresh token travels only in the HttpOnly cookie.

        A copy in the JSON body is readable by any script on the page, which
        turns an XSS into a 30-day session the user cannot see or revoke.
        """
        response = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )

        assert response.status_code == status.HTTP_200_OK
        assert 'refresh_token' not in response.json()
        assert response.cookies.get('refresh_token')

        refreshed = client.post('/api/v1/auth/refresh')
        assert refreshed.status_code == status.HTTP_200_OK, refreshed.text
        assert 'access_token' in refreshed.json()
        assert 'refresh_token' not in refreshed.json()

    def test_login_wrong_email(self, client, test_user):
        """Tests login with wrong email."""
        response = client.post(
            '/api/v1/auth/login',
            data={'username': 'wrong@example.com', 'password': 'testpassword123'},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert 'Invalid email or password' in response.json()['detail']['message']

    def test_login_wrong_password(self, client, test_user):
        """Tests login with wrong password."""
        response = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'wrongpassword'},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert 'Invalid email or password' in response.json()['detail']['message']

    def test_login_missing_credentials(self, client):
        """Tests login without credentials."""
        response = client.post('/api/v1/auth/login', data={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestPasswordByteCeiling:
    """bcrypt refuses passwords longer than 72 bytes instead of truncating
    them, so the doors around it must answer for the limit themselves: a
    registration gets the policy sentence in the request's language, and a
    login answers exactly like a wrong password — for a known account and an
    unknown one alike, so the status code stops telling the two apart."""

    #: 73 bytes in UTF-8: 35 two-byte letters plus 'Aa1'. It passes every
    #: character rule (8..128 chars, upper, lower, digit) and breaks only the
    #: byte ceiling.
    past_the_ceiling = 'Ą' * 35 + 'Aa1'

    def test_register_refuses_a_password_past_the_byte_ceiling(self, client):
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'toolong@example.com',
                'password': self.past_the_ceiling,
                'full_name': 'Too Long',
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'bytes' in response.text
        assert 'bcrypt' not in response.text.lower()
        assert 'truncate' not in response.text.lower()

    def test_register_byte_ceiling_message_follows_the_request_language(self, client):
        response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'toolong-pl@example.com',
                'password': self.past_the_ceiling,
                'full_name': 'Za Długie',
            },
            headers={'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.8'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        (entry,) = response.json()['detail']
        assert 'bajty' in entry['msg']
        assert entry['code'] == 'PASSWORD_TOO_LONG'
        # The entry's ctx names the catalogue argument (max_bytes), so the
        # English sentence is what must not appear, not the word.
        assert 'bytes long' not in response.text

    def test_login_with_a_password_past_the_byte_ceiling_answers_like_a_wrong_password(
        self, client, test_user
    ):
        response = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': self.past_the_ceiling},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        detail = response.json()['detail']
        assert detail['code'] == 'INVALID_CREDENTIALS'
        assert 'bcrypt' not in response.text.lower()
        assert 'truncate' not in response.text.lower()

    def test_login_byte_ceiling_known_and_unknown_account_answer_identically(
        self, client, test_user
    ):
        known = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': self.past_the_ceiling},
        )
        unknown = client.post(
            '/api/v1/auth/login',
            data={
                'username': 'nobody@example.com',
                'password': self.past_the_ceiling,
            },
        )

        assert known.status_code == unknown.status_code == status.HTTP_401_UNAUTHORIZED
        assert known.json()['detail'] == unknown.json()['detail']


@pytest.mark.integration
class TestLoginFailedLogIp:
    """Failed-login warning must include the client IP for forensic analysis."""

    def test_failed_login_log_ignores_a_forged_xff(self, client, test_user, caplog):
        """the app must not read X-Forwarded-For itself.

        Uvicorn rewrites ``scope['client']`` from that header when the peer is
        a trusted proxy, so parsing it here would let any caller write the IP
        that an operator reads while investigating an attack.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger='app.services.auth_service'):
            response = client.post(
                '/api/v1/auth/login',
                data={
                    'username': test_user.email,
                    'password': 'WrongPassword123',
                },
                headers={'X-Forwarded-For': '203.0.113.42'},
            )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        messages = [r.getMessage() for r in caplog.records]
        assert not any('203.0.113.42' in m for m in messages), (
            f'Forged X-Forwarded-For reached the log: {messages}'
        )
        assert any('from IP ' in m for m in messages), messages

    def test_failed_login_log_unknown_ip_without_xff(self, client, test_user, caplog):
        """Without X-Forwarded-For, the warning still resolves to an IP value (not dangling)."""
        import logging

        with caplog.at_level(logging.WARNING, logger='app.services.auth_service'):
            client.post(
                '/api/v1/auth/login',
                data={
                    'username': test_user.email,
                    'password': 'WrongPassword123',
                },
            )
        messages = [r.getMessage() for r in caplog.records]
        # Must NOT be the old dangling format ending in 'from IP' (no value).
        assert not any(m.rstrip().endswith('from IP') for m in messages), (
            f'Dangling "from IP" without value in: {messages}'
        )
        # And it must contain an actual IP value (testclient host or "unknown").
        assert any(
            'from IP ' in m and (m.endswith('unknown') or 'testclient' in m)
            for m in messages
        ), f'Expected IP value in failed-login log; got: {messages}'


@pytest.mark.integration
class TestAuthRefresh:
    """Tests for token refresh endpoint."""

    def test_refresh_token_success(self, client, test_user):
        """Tests successful token refresh."""
        # First login
        login_response = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        token = login_response.json()['access_token']

        # Refresh token
        response = client.post(
            '/api/v1/auth/refresh', headers={'Authorization': f'Bearer {token}'}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'access_token' in data
        assert data['token_type'] == 'bearer'

    def test_refresh_token_invalid_cookie(self, client):
        """An unreadable cookie is a refusal, not a missing session."""
        client.cookies.set('refresh_token', 'not-a-token')
        response = client.post('/api/v1/auth/refresh')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_token_missing(self, client):
        """No cookie answers 204 — there is simply no session to refresh.

        The boot probe asks this on every cold load; a refusal here is the
        ordinary answer of a visitor who has not signed in, and a 4xx made
        every browser log an error for it.
        """
        response = client.post('/api/v1/auth/refresh')

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b''

    def test_refresh_token_reuse_within_grace_rotates_again(
        self, client, test_user, monkeypatch
    ):
        """Recent refresh-token reuse should recover by issuing a new cookie."""
        from app.core.token_blacklist import token_blacklist

        login_response = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        refresh_token = login_response.cookies['refresh_token']

        async def is_revoked(token: str) -> bool:
            return token == refresh_token

        async def get_revoked_at(token: str):
            return datetime.now(tz=UTC) if token == refresh_token else None

        async def is_user_revoked(user_id: str, session_id: str = '') -> bool:
            return False

        monkeypatch.setattr(token_blacklist, 'is_revoked', is_revoked)
        monkeypatch.setattr(token_blacklist, 'get_revoked_at', get_revoked_at)
        monkeypatch.setattr(token_blacklist, 'is_user_revoked', is_user_revoked)

        client.cookies.set('refresh_token', refresh_token)
        response = client.post('/api/v1/auth/refresh')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'access_token' in data
        assert response.cookies['refresh_token'] != refresh_token


@pytest.mark.integration
class TestUploadsAuthMiddleware:
    """Tests for uploads auth middleware — refresh token expiry check."""

    def test_expired_refresh_token_rejected(self, client, test_user):
        """An expired refresh token in cookie must be rejected with 401."""
        expired_payload = {
            'sub': str(test_user.id),
            'exp': int(time.time()) - 3600,
        }
        expired_token = pyjwt.encode(
            expired_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )

        client.cookies.set('refresh_token', expired_token)
        response = client.get('/uploads/test.txt')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_valid_bearer_token_accepted(self, client, test_user):
        """A valid Bearer access token must be accepted for uploads."""
        from app.services.token_service import create_access_token

        access_token = create_access_token(
            data={'sub': str(test_user.id), 'sid': 'test-session'}
        )

        response = client.get(
            '/uploads/nonexistent.txt',
            headers={'Authorization': f'Bearer {access_token}'},
        )

        assert response.status_code != status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestAuthLogout:
    """Tests for logout endpoint."""

    def test_logout_success(self, client, auth_headers):
        """Tests successful logout."""
        response = client.post('/api/v1/auth/logout', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['message'] == 'Logged out successfully'

    def test_logout_without_auth(self, client):
        """Tests logout without authorization (cookie-only flow)."""
        response = client.post('/api/v1/auth/logout')

        # Logout doesn't require authorization
        assert response.status_code == status.HTTP_200_OK

    # A revoked access token answering 401 is asserted, with a store wired in,
    # by test_logging_out_ends_the_session.py. The test here waited for a Redis
    # that TESTING never connects, so it skipped in every run it ever had.


@pytest.mark.integration
class TestAuthMe:
    """Tests for get user profile endpoint."""

    def test_get_me_success(self, client, test_user, auth_headers):
        """Tests successful user profile fetching."""
        response = client.get('/api/v1/auth/me', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_user.id)
        assert data['email'] == test_user.email
        assert data['full_name'] == test_user.full_name
        assert 'hashed_password' not in data

    def test_login_local_domain_email_200(
        self, client, db_session: Session, test_household
    ):
        """Intranet emails (e.g. qa@inventari.local) login + /auth/me.

        UserRead.email was typed EmailStr, which rejects non-deliverable TLDs
        like '.local' during response serialization → HTTP 500 on GET /auth/me
        and a silent login screen. A looser validator now permits local domains.
        """
        from app.models.user import User
        from app.services.token_service import get_password_hash

        user = User(
            email='qa@inventari.local',
            hashed_password=get_password_hash('testpassword123'),
            full_name='Intranet User',
            organization_id=test_household.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        login = client.post(
            '/api/v1/auth/login',
            data={'username': 'qa@inventari.local', 'password': 'testpassword123'},
        )
        assert login.status_code == status.HTTP_200_OK
        token = login.json()['access_token']

        me = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
        assert me.status_code == status.HTTP_200_OK
        assert me.json()['email'] == 'qa@inventari.local'

    def test_get_me_unauthorized(self, client):
        """A request with no credential answers the coded envelope.

        The scheme's own refusal was the framework's bare English
        ``{"detail": "Not authenticated"}``: the one 401 of an authenticated
        route a client could not branch on, and the one a Polish reader got
        in English.
        """
        response = client.get('/api/v1/auth/me', headers={'Accept-Language': 'pl'})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()['detail'] == {
            'code': 'NOT_AUTHENTICATED',
            'message': 'Nie jesteś zalogowany',
            'lang': 'pl',
        }
        assert response.headers['WWW-Authenticate'] == 'Bearer'

    def test_get_me_invalid_token(self, client):
        """Tests fetching profile with invalid token."""
        response = client.get(
            '/api/v1/auth/me', headers={'Authorization': 'Bearer invalid_token'}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        # A code a client can branch on, beside the sentence; the challenge
        # header stays where the auth layer reads it.
        assert response.json()['detail']['code'] == 'TOKEN_INVALID'
        assert response.headers['WWW-Authenticate'] == 'Bearer'

    def test_get_me_wrong_user_token(self, client, auth_headers_user2):
        """Tests fetching profile with another user's token."""
        response = client.get('/api/v1/auth/me', headers=auth_headers_user2)

        # Should return user profile from token
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['email'] == 'test2@example.com'


@pytest.mark.integration
class TestGetMeNoSideEffect:
    """GET /auth/me must be side-effect-free — no user creation in the handler."""

    def test_get_me_does_not_create_user(
        self, client, db_session: Session, auth_headers
    ):
        """A normal authenticated GET /me must not write to the users table."""
        from sqlalchemy import func, select

        from app.models.user import User

        before = db_session.execute(select(func.count()).select_from(User)).scalar_one()
        response = client.get('/api/v1/auth/me', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        after = db_session.execute(select(func.count()).select_from(User)).scalar_one()
        assert after == before

    def test_get_me_user_without_org_does_not_self_register(
        self, client, db_session: Session
    ):
        """A user with organization_id=None calling /me must NOT trigger a new user row."""
        from sqlalchemy import func, select

        from app.models.user import User
        from app.services.token_service import create_access_token

        orphan = User(
            email='orphan@example.com',
            hashed_password='x',
            organization_id=None,
            is_active=True,
        )
        db_session.add(orphan)
        db_session.commit()
        db_session.refresh(orphan)

        before = db_session.execute(select(func.count()).select_from(User)).scalar_one()
        token = create_access_token(data={'sub': str(orphan.id)})
        headers = {'Authorization': f'Bearer {token}'}

        response = client.get('/api/v1/auth/me', headers=headers)

        # The row is committed above, so /me answers 200; the 404 in
        # api/auth/_profile.py fires only when auth_service finds no user at
        # all. The claim this test exists for is the one below it: no write.
        assert response.status_code == status.HTTP_200_OK
        after = db_session.execute(select(func.count()).select_from(User)).scalar_one()
        assert after == before, (
            f'GET /me must not create users; count went {before} -> {after}'
        )


@pytest.mark.integration
class TestAuthFlow:
    """Tests for complete authorization flow."""

    def test_complete_auth_flow(self, client):
        """Tests complete flow: register -> login -> get profile."""
        # 1. Register
        register_response = client.post(
            '/api/v1/auth/register',
            json={
                'email': 'flowtest@example.com',
                'password': 'Password123',
                'full_name': 'Flow Test User',
            },
        )
        assert register_response.status_code == status.HTTP_201_CREATED

        # 2. Login
        login_response = client.post(
            '/api/v1/auth/login',
            data={'username': 'flowtest@example.com', 'password': 'Password123'},
        )
        assert login_response.status_code == status.HTTP_200_OK
        token = login_response.json()['access_token']

        # 3. Get profile
        me_response = client.get(
            '/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'}
        )
        assert me_response.status_code == status.HTTP_200_OK
        data = me_response.json()
        assert data['email'] == 'flowtest@example.com'
        assert data['full_name'] == 'Flow Test User'
