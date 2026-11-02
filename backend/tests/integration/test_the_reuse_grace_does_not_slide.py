"""A stolen refresh cookie must run out of forgiveness.

Rotation blacklists the refresh token it consumed. A replay arriving within
``REFRESH_REUSE_GRACE_SECONDS`` of that moment is forgiven on purpose — a
StrictMode double-mount, a mobile reload and a second tab all send the same
cookie twice within milliseconds, and treating that as an attack would log
people out for using the product normally.

The forgiven request then rotated again, and the second revocation of the
same token wrote a fresh timestamp. The window was therefore measured from
the *last* replay rather than from the rotation, so a cookie replayed every
few seconds was forgiven indefinitely and minted a token pair every time,
without ever tripping reuse detection.

The window now runs from the moment the token was first revoked, and nothing
moves it. Every documented concurrency case still fits inside it; a thief
replaying the cookie a few seconds later does not.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import status

from app.api.auth._tokens import REFRESH_REUSE_GRACE_SECONDS
from app.core.token_blacklist import token_blacklist
from tests.integration._fake_token_store import FakeTokenStore

PASSWORD = 'testpassword123'


@pytest.fixture
def blacklist_on() -> Any:
    """Give the blacklist a store, so revocation actually means something.

    Without Redis the whole mechanism fails open in test mode and every
    assertion below would pass for the wrong reason.
    """
    previous = token_blacklist._redis
    fake = FakeTokenStore()
    token_blacklist.set_redis(fake)
    yield fake
    token_blacklist._redis = previous


def _login(client, user) -> str:
    resp = client.post(
        '/api/v1/auth/login',
        data={'username': user.email, 'password': PASSWORD},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return resp.cookies['refresh_token']


def _refresh_with(client, cookie: str):
    client.cookies.set('refresh_token', cookie)
    return client.post('/api/v1/auth/refresh')


def _key(token: str) -> str:
    return f'{token_blacklist.PREFIX}{token}'


def _age_the_revocation(fake, token: str, seconds: int) -> str:
    """Backdate a revocation by *seconds*, and answer with the new value.

    Backdating beats sleeping: the stored timestamp has one-second
    resolution, so a test that waits out a real window would need several
    seconds of sleep to stay clear of the rounding.
    """
    key = _key(token)
    aged = str(int(fake.store[key]) - seconds)
    fake.store[key] = aged
    return aged


@pytest.mark.integration
class TestTheGraceWindowIsAnchored:
    def test_a_replay_inside_the_window_is_still_forgiven(
        self, client, blacklist_on, test_user
    ):
        """The reason the window exists in the first place."""
        first = _login(client, test_user)

        assert _refresh_with(client, first).status_code == status.HTTP_200_OK
        assert _refresh_with(client, first).status_code == status.HTTP_200_OK

    def test_forgiving_a_replay_does_not_move_the_window(
        self, client, blacklist_on, test_user
    ):
        first = _login(client, test_user)
        _refresh_with(client, first)
        revoked_at = _age_the_revocation(blacklist_on, first, 2)

        assert _refresh_with(client, first).status_code == status.HTTP_200_OK

        assert blacklist_on.store[_key(first)] == revoked_at

    def test_the_window_runs_out_however_often_the_cookie_comes_back(
        self, client, blacklist_on, test_user
    ):
        first = _login(client, test_user)
        _refresh_with(client, first)

        # Two seconds of window left, then replayed twice — which is exactly
        # the pattern that used to keep the grace alive for ever.
        _age_the_revocation(blacklist_on, first, REFRESH_REUSE_GRACE_SECONDS - 2)
        assert _refresh_with(client, first).status_code == status.HTTP_200_OK

        time.sleep(2.5)
        refused = _refresh_with(client, first)

        assert refused.status_code == status.HTTP_401_UNAUTHORIZED, refused.text
        assert refused.json()['detail']['code'] == 'TOKEN_REVOKED'

    def test_running_out_revokes_the_whole_family(
        self, client, blacklist_on, test_user
    ):
        first = _login(client, test_user)
        rotated = _refresh_with(client, first).cookies['refresh_token']
        _age_the_revocation(blacklist_on, first, REFRESH_REUSE_GRACE_SECONDS + 5)

        _refresh_with(client, first)

        # The token the legitimate holder was rotated onto dies with the
        # family — that is what reuse detection is for.
        assert (
            _refresh_with(client, rotated).status_code == status.HTTP_401_UNAUTHORIZED
        )
