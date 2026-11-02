"""Logging out has to end the session, not the two tokens in the request.

Logout blacklisted the access token in the header and the refresh cookie, and
stopped there. Everything else minted under the same ``sid`` — the access
tokens an earlier rotation handed out, still inside their half-hour — went on
answering. "Log me out" is a statement about the session, and a session is
exactly what the family marker names.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import status

from app.core.token_blacklist import token_blacklist
from tests.integration._fake_token_store import FakeTokenStore

PASSWORD = 'testpassword123'


@pytest.fixture
def blacklist_on() -> Any:
    previous = token_blacklist._redis  # noqa: SLF001
    fake = FakeTokenStore()
    token_blacklist.set_redis(fake)
    yield fake
    token_blacklist._redis = previous  # noqa: SLF001


def _login(client, user) -> str:
    resp = client.post(
        '/api/v1/auth/login',
        data={'username': user.email, 'password': PASSWORD},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return resp.json()['access_token']


def _me(client, access: str):
    return client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {access}'})


@pytest.mark.integration
class TestLogoutEndsTheWholeSession:
    def test_a_sibling_token_of_the_same_session_stops_working(
        self, client, blacklist_on, test_user
    ):
        first = _login(client, test_user)

        # Rotate: the session now has a second access token, and the first one
        # is still inside its lifetime. Logout is sent with the newer one.
        # The second has to be a *different* string — `iat`/`exp` are whole
        # seconds, so two tokens minted in the same second are byte-identical
        # and blacklisting one would look like blacklisting both.
        time.sleep(1.1)
        rotated = client.post('/api/v1/auth/refresh')
        assert rotated.status_code == status.HTTP_200_OK, rotated.text
        second = rotated.json()['access_token']
        assert second != first
        assert _me(client, first).status_code == status.HTTP_200_OK

        client.post(
            '/api/v1/auth/logout', headers={'Authorization': f'Bearer {second}'}
        )

        assert _me(client, first).status_code == status.HTTP_401_UNAUTHORIZED
        assert _me(client, second).status_code == status.HTTP_401_UNAUTHORIZED

    def test_the_refresh_cookie_of_that_session_stops_too(
        self, client, blacklist_on, test_user
    ):
        access = _login(client, test_user)
        cookie = client.cookies['refresh_token']

        client.post(
            '/api/v1/auth/logout', headers={'Authorization': f'Bearer {access}'}
        )

        # Logout clears the cookie in the browser; whoever copied it before
        # that still holds the string, so the server has to refuse it.
        client.cookies.set('refresh_token', cookie)
        refused = client.post('/api/v1/auth/refresh')

        assert refused.status_code == status.HTTP_401_UNAUTHORIZED, refused.text

    def test_another_session_of_the_same_user_is_untouched(
        self, client, blacklist_on, test_user
    ):
        """Logging out of one device is not logging out of every device."""
        first_device = _login(client, test_user)
        client.cookies.clear()
        second_device = _login(client, test_user)

        client.post(
            '/api/v1/auth/logout', headers={'Authorization': f'Bearer {first_device}'}
        )

        assert _me(client, first_device).status_code == status.HTTP_401_UNAUTHORIZED
        assert _me(client, second_device).status_code == status.HTTP_200_OK

    def test_logging_in_again_works(self, client, blacklist_on, test_user):
        access = _login(client, test_user)
        client.post(
            '/api/v1/auth/logout', headers={'Authorization': f'Bearer {access}'}
        )
        client.cookies.clear()
        time.sleep(1.1)  # a fresh login must mint a different token string

        assert _me(client, _login(client, test_user)).status_code == status.HTTP_200_OK
