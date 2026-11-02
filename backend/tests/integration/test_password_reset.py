"""Integration tests for the password-reset endpoints.

Security guarantees under test:
- ``POST /auth/password-reset/request`` always returns 202, even when the
  email is unknown, so attackers cannot enumerate registered addresses.
- ``POST /auth/password-reset/confirm`` rejects bad/forged tokens with 400.
- A valid token rotates the password and the user can immediately log in
  with the new credential.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.services.email_service import EmailService
from app.services.token_service import create_password_reset_token
from tests.integration._fake_token_store import FakeTokenStore


@pytest.mark.integration
class TestPasswordReset:
    def test_request_returns_202_for_unknown_email(self, client: TestClient) -> None:
        """Endpoint must NOT reveal whether the email exists."""
        response = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': 'nobody@nowhere.example'},
        )
        assert response.status_code == 202

    def test_request_sends_email_for_known_user(
        self,
        client: TestClient,
        test_user,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """For a registered email, exactly one reset email is dispatched."""
        sent: list[tuple[str, str, str]] = []

        async def _capture(
            to_email: str, reset_link: str, lang: str = 'en', **kwargs
        ) -> bool:
            sent.append((to_email, reset_link, lang))
            return True

        monkeypatch.setattr(
            EmailService,
            'send_password_reset_email_async',
            _capture,
        )
        response = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': test_user.email},
        )
        assert response.status_code == 202
        assert len(sent) == 1
        to_email, reset_link, _lang = sent[0]
        assert to_email == test_user.email
        assert '/reset-password/' in reset_link

    def test_request_reports_that_the_installation_cannot_send_mail(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without SMTP the screen must not promise a letter nobody will send."""
        monkeypatch.setattr(EmailService, 'is_configured', lambda *a, **k: False)
        response = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': 'nobody@nowhere.example'},
        )
        assert response.status_code == 202
        assert response.json()['email_delivery_configured'] is False

    def test_the_reset_mail_is_sent_with_the_organizations_mail_server(
        self,
        client: TestClient,
        test_user,
        test_household,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Mail set up in Settings carries the reset, not the empty system config."""
        test_household.settings = {
            'smtp': {'host': 'relay.example.test', 'port': 25, 'encryption': 'none'}
        }
        db_session.commit()
        queued: list[dict] = []

        async def _capture(*args, **kwargs) -> bool:
            queued.append(kwargs)
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', _capture)
        response = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': test_user.email},
        )
        assert response.status_code == 202
        (kwargs,) = queued
        assert kwargs['smtp_config']['host'] == 'relay.example.test'

    def test_the_flag_reads_mail_set_up_in_settings(
        self,
        client: TestClient,
        test_household,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An install configured only through Settings still sends mail."""
        monkeypatch.setattr('app.services.email_service.settings.SMTP_HOST', None)
        before = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': 'nobody@nowhere.example'},
        )
        assert before.json()['email_delivery_configured'] is False

        test_household.settings = {
            'smtp': {'host': 'relay.example.test', 'port': 25, 'encryption': 'none'}
        }
        db_session.commit()
        after = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': 'nobody@nowhere.example'},
        )
        assert after.json()['email_delivery_configured'] is True

    def test_delivery_flag_does_not_depend_on_the_address(
        self,
        client: TestClient,
        test_user,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The flag describes the installation, so it cannot enumerate accounts."""
        monkeypatch.setattr(EmailService, 'is_configured', lambda *a, **k: True)

        async def _capture(*args, **kwargs) -> bool:
            return True

        monkeypatch.setattr(EmailService, 'send_password_reset_email_async', _capture)
        known = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': test_user.email},
        )
        unknown = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': 'nobody@nowhere.example'},
        )
        assert known.json() == unknown.json()

    def test_confirm_with_valid_token_changes_password(
        self,
        client: TestClient,
        test_user,
        db_session,
    ) -> None:
        """A valid token rotates the password and the user can log in."""
        token = create_password_reset_token(test_user.id)
        new_password = 'NewStrong123'

        response = client.post(
            '/api/v1/auth/password-reset/confirm',
            json={'token': token, 'new_password': new_password},
        )
        assert response.status_code == 200

        # Old password no longer works
        old_login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        assert old_login.status_code == 401

        # New password works
        new_login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': new_password},
        )
        assert new_login.status_code == 200

    def test_confirm_with_invalid_token_returns_400(
        self, client: TestClient, test_user
    ) -> None:
        """A forged/garbage token must be rejected without touching the user."""
        response = client.post(
            '/api/v1/auth/password-reset/confirm',
            json={'token': 'not.a.valid.jwt', 'new_password': 'NewStrong123'},
        )
        assert response.status_code == 400
        # The router caught the service's refusal and answered a bare string.
        assert response.json()['detail']['code'] == 'INVALID_RESET_TOKEN'

    def test_confirm_with_wrong_type_token_returns_400(
        self, client: TestClient, test_user
    ) -> None:
        """A regular access token (without the ``password_reset`` claim) is rejected."""
        from app.services.token_service import create_access_token

        fake = create_access_token(
            data={'sub': str(test_user.id)},
            expires_delta=__import__('datetime').timedelta(minutes=5),
        )
        response = client.post(
            '/api/v1/auth/password-reset/confirm',
            json={'token': fake, 'new_password': 'NewStrong123'},
        )
        assert response.status_code == 400

    def test_reset_invalidates_sessions_issued_before_it(
        self, client: TestClient, test_user, db_session
    ) -> None:
        """A refresh token stolen before the reset must stop working.

        Redis is injected as an in-memory stand-in so the marker survives
        between requests exactly as it does in production.
        """
        import time

        from app.core.token_blacklist import token_blacklist

        original_redis = token_blacklist._redis  # noqa: SLF001
        token_blacklist.set_redis(FakeTokenStore())  # type: ignore[arg-type]
        try:
            login = client.post(
                '/api/v1/auth/login',
                data={'username': test_user.email, 'password': 'testpassword123'},
            )
            assert login.status_code == 200
            stolen_refresh = login.cookies['refresh_token']
            stolen_access = login.json()['access_token']

            # The session works before the reset. Deliberately NOT exercised
            # via /auth/refresh — rotation would blacklist the token and the
            # later 401 would prove nothing.
            assert (
                client.get(
                    '/api/v1/auth/me',
                    headers={'Authorization': f'Bearer {stolen_access}'},
                ).status_code
                == 200
            )

            reset = client.post(
                '/api/v1/auth/password-reset/confirm',
                json={
                    'token': create_password_reset_token(test_user.id),
                    'new_password': 'NewStrong123',
                },
            )
            assert reset.status_code == 200

            client.cookies.set('refresh_token', stolen_refresh)
            assert client.post('/api/v1/auth/refresh').status_code == 401

            assert (
                client.get(
                    '/api/v1/auth/me',
                    headers={'Authorization': f'Bearer {stolen_access}'},
                ).status_code
                == 401
            )

            # A fresh login is unaffected. ``iat`` has one-second granularity,
            # so a login inside the same second as the reset is (deliberately)
            # still treated as older than the marker.
            time.sleep(1.1)
            client.cookies.clear()
            relogin = client.post(
                '/api/v1/auth/login',
                data={'username': test_user.email, 'password': 'NewStrong123'},
            )
            assert relogin.status_code == 200
            # The login already set the cookie; refresh rides on it.
            assert client.post('/api/v1/auth/refresh').status_code == 200
        finally:
            token_blacklist._redis = original_redis  # noqa: SLF001

    def test_profile_password_change_revokes_but_name_change_does_not(
        self, client: TestClient, test_user, db_session
    ) -> None:
        """PATCH /me kills other sessions only when the password moves."""
        from app.core.token_blacklist import token_blacklist

        original_redis = token_blacklist._redis  # noqa: SLF001
        token_blacklist.set_redis(FakeTokenStore())  # type: ignore[arg-type]
        try:
            login = client.post(
                '/api/v1/auth/login',
                data={'username': test_user.email, 'password': 'testpassword123'},
            )
            access = login.json()['access_token']
            headers = {'Authorization': f'Bearer {access}'}

            # Renaming leaves the session alone.
            assert (
                client.patch(
                    '/api/v1/auth/me', json={'full_name': 'Renamed'}, headers=headers
                ).status_code
                == 200
            )
            assert client.get('/api/v1/auth/me', headers=headers).status_code == 200

            # Changing the password does not.
            assert (
                client.patch(
                    '/api/v1/auth/me',
                    json={
                        'password': 'NewStrong123',
                        # The current password is mandatory here.
                        'current_password': 'testpassword123',
                    },
                    headers=headers,
                ).status_code
                == 200
            )
            assert client.get('/api/v1/auth/me', headers=headers).status_code == 401
        finally:
            token_blacklist._redis = original_redis  # noqa: SLF001

    def test_short_password_is_rejected_by_pydantic(
        self, client: TestClient, test_user
    ) -> None:
        """Password complexity / length is enforced at the schema layer."""
        token = create_password_reset_token(test_user.id)
        response = client.post(
            '/api/v1/auth/password-reset/confirm',
            json={'token': token, 'new_password': 'short'},
        )
        assert response.status_code == 422

    def test_confirm_refuses_a_password_past_the_byte_ceiling(
        self, client: TestClient, test_user
    ) -> None:
        """bcrypt refuses passwords longer than 72 bytes instead of
        truncating them; the reset door refuses the value with the policy
        sentence, never the library's, and the old password stays working."""
        #: 73 bytes in UTF-8: 35 two-byte letters plus 'Aa1' — passes every
        #: character rule, breaks only the byte ceiling.
        past_the_ceiling = 'Ą' * 35 + 'Aa1'
        token = create_password_reset_token(test_user.id)
        response = client.post(
            '/api/v1/auth/password-reset/confirm',
            json={'token': token, 'new_password': past_the_ceiling},
        )
        assert response.status_code == 422
        assert 'bytes' in response.text
        assert 'bcrypt' not in response.text.lower()
        assert 'truncate' not in response.text.lower()
        assert (
            client.post(
                '/api/v1/auth/login',
                data={'username': test_user.email, 'password': 'testpassword123'},
            ).status_code
            == 200
        ), 'the old password must still work after a refused reset'


@pytest.mark.integration
class TestTokenTypeSeparation:
    """Access and refresh tokens had identical shape, so a refresh
    token sent as a Bearer header authenticated requests for 30 days."""

    def test_refresh_token_is_rejected_as_bearer(
        self, client: TestClient, test_user
    ) -> None:
        login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        assert login.status_code == 200
        refresh_token = login.cookies['refresh_token']

        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': f'Bearer {refresh_token}'},
        )

        assert response.status_code == 401

    def test_access_token_is_rejected_on_refresh(
        self, client: TestClient, test_user
    ) -> None:
        login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        access_token = login.json()['access_token']

        client.cookies.set('refresh_token', access_token)
        assert client.post('/api/v1/auth/refresh').status_code == 401

    def test_normal_login_and_refresh_flow_still_works(
        self, client: TestClient, test_user
    ) -> None:
        login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        body = login.json()
        assert (
            client.get(
                '/api/v1/auth/me',
                headers={'Authorization': f'Bearer {body["access_token"]}'},
            ).status_code
            == 200
        )

        refreshed = client.post('/api/v1/auth/refresh')
        assert refreshed.status_code == 200
        # Not comparing token strings: minted in the same second with the same
        # claims, they are byte-identical.
        assert refreshed.json()['access_token']

    def test_token_without_type_claim_is_rejected(
        self, client: TestClient, test_user
    ) -> None:
        """Tokens minted before the type claim carry none — one forced logout."""
        import jwt

        from app.config import settings

        legacy = jwt.encode(
            {
                'sub': str(test_user.id),
                'exp': int(time.time()) + 3600,
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )

        response = client.get(
            '/api/v1/auth/me', headers={'Authorization': f'Bearer {legacy}'}
        )

        assert response.status_code == 401


@pytest.mark.integration
class TestLoginResponseIsUniform:
    """A non-existent account, a wrong password and a blocked account
    must be indistinguishable from the outside."""

    def test_all_failure_modes_share_status_and_body(
        self, client: TestClient, test_user, db_session
    ) -> None:
        unknown = client.post(
            '/api/v1/auth/login',
            data={'username': 'nobody@nowhere.example', 'password': 'whatever123'},
        )
        wrong_password = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'definitely-wrong'},
        )

        test_user.is_blocked = True
        test_user.blocking_reason = 'Policy violation'
        db_session.commit()
        blocked = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )

        assert unknown.status_code == wrong_password.status_code == 401
        assert blocked.status_code == 401
        assert unknown.json() == wrong_password.json() == blocked.json()
        assert 'Policy violation' not in blocked.text


@pytest.mark.integration
class TestPasswordChangeHardening:
    """Re-authenticate on password change; burn the reset token."""

    def test_profile_password_change_requires_current_password(
        self, client: TestClient, test_user
    ) -> None:
        login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        headers = {'Authorization': f'Bearer {login.json()["access_token"]}'}

        response = client.patch(
            '/api/v1/auth/me', json={'password': 'NewStrong123'}, headers=headers
        )

        assert response.status_code == 400, response.text
        assert (
            client.post(
                '/api/v1/auth/login',
                data={'username': test_user.email, 'password': 'testpassword123'},
            ).status_code
            == 200
        ), 'the old password must still work after a refused change'

    def test_profile_password_change_refuses_past_the_byte_ceiling(
        self, client: TestClient, test_user
    ) -> None:
        """The change door answers for the bcrypt byte ceiling the same way
        the reset door does — the policy sentence, not the library's."""
        #: 73 bytes in UTF-8: 35 two-byte letters plus 'Aa1'.
        past_the_ceiling = 'Ą' * 35 + 'Aa1'
        login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        headers = {'Authorization': f'Bearer {login.json()["access_token"]}'}

        response = client.patch(
            '/api/v1/auth/me',
            json={'password': past_the_ceiling, 'current_password': 'testpassword123'},
            headers=headers,
        )

        assert response.status_code == 422, response.text
        assert 'bytes' in response.text
        assert 'bcrypt' not in response.text.lower()
        assert 'truncate' not in response.text.lower()
        assert (
            client.post(
                '/api/v1/auth/login',
                data={'username': test_user.email, 'password': 'testpassword123'},
            ).status_code
            == 200
        ), 'the old password must still work after a refused change'

    def test_profile_password_change_succeeds_with_current_password(
        self, client: TestClient, test_user
    ) -> None:
        login = client.post(
            '/api/v1/auth/login',
            data={'username': test_user.email, 'password': 'testpassword123'},
        )
        headers = {'Authorization': f'Bearer {login.json()["access_token"]}'}

        response = client.patch(
            '/api/v1/auth/me',
            json={
                'password': 'NewStrong123',
                'current_password': 'testpassword123',
            },
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert (
            client.post(
                '/api/v1/auth/login',
                data={'username': test_user.email, 'password': 'NewStrong123'},
            ).status_code
            == 200
        )

    def test_reset_token_works_only_once(self, client: TestClient, test_user) -> None:
        from app.core.token_blacklist import token_blacklist

        original_redis = token_blacklist._redis  # noqa: SLF001
        token_blacklist.set_redis(FakeTokenStore())  # type: ignore[arg-type]
        try:
            token = create_password_reset_token(test_user.id)

            first = client.post(
                '/api/v1/auth/password-reset/confirm',
                json={'token': token, 'new_password': 'NewStrong123'},
            )
            second = client.post(
                '/api/v1/auth/password-reset/confirm',
                json={'token': token, 'new_password': 'EvenNewer123'},
            )

            assert first.status_code == 200, first.text
            assert second.status_code == 400, second.text
            assert (
                client.post(
                    '/api/v1/auth/login',
                    data={'username': test_user.email, 'password': 'NewStrong123'},
                ).status_code
                == 200
            ), 'the replay must not have changed the password again'
        finally:
            token_blacklist._redis = original_redis  # noqa: SLF001
