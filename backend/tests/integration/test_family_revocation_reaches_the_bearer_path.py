"""Revoking a session family has to reach the access tokens it minted.

Reuse detection revokes a whole family, and so does a GDPR delete. Until now
the marker was consulted in exactly two places — ``/auth/refresh`` and the
media cookie — while ordinary requests carrying ``Authorization: Bearer``
checked only the per-token blacklist. An attacker caught replaying a stolen
refresh cookie therefore kept a working access token for up to its natural
lifetime, which is the half-hour after the moment the system decided it was
under attack.
"""

from __future__ import annotations

from typing import Any

import jwt
import pytest
from fastapi import status

from app.api.auth._tokens import REFRESH_REUSE_GRACE_SECONDS
from app.config import settings
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


def _login(client, user) -> tuple[str, str]:
    """Log in and answer with (access token, refresh cookie)."""
    resp = client.post(
        '/api/v1/auth/login',
        data={'username': user.email, 'password': PASSWORD},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return resp.json()['access_token'], resp.cookies['refresh_token']


def _me(client, access_token: str):
    return client.get(
        '/api/v1/auth/me', headers={'Authorization': f'Bearer {access_token}'}
    )


def _family_of(access_token: str) -> tuple[str, str]:
    payload = jwt.decode(
        access_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    return payload['sub'], payload['sid']


@pytest.mark.integration
class TestARevokedFamilyStopsAnsweringOnBearer:
    def test_reuse_detection_kills_the_access_token_it_already_minted(
        self, client, blacklist_on, test_user
    ):
        access, refresh = _login(client, test_user)
        assert _me(client, access).status_code == status.HTTP_200_OK

        # Rotate, then replay the consumed cookie once the grace window has
        # run out — the sequence that means "someone else has this cookie".
        client.cookies.set('refresh_token', refresh)
        client.post('/api/v1/auth/refresh')
        key = f'{token_blacklist.PREFIX}{refresh}'
        blacklist_on.store[key] = str(
            int(blacklist_on.store[key]) - REFRESH_REUSE_GRACE_SECONDS - 5
        )
        client.cookies.set('refresh_token', refresh)
        client.post('/api/v1/auth/refresh')

        assert _me(client, access).status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_only_the_revoked_family_is_affected(
        self, client, blacklist_on, test_user
    ):
        first_access, _ = _login(client, test_user)
        client.cookies.clear()
        second_access, _ = _login(client, test_user)

        user_id, first_family = _family_of(first_access)
        await token_blacklist.revoke_user_family(user_id, first_family)

        assert _me(client, first_access).status_code == status.HTTP_401_UNAUTHORIZED
        assert _me(client, second_access).status_code == status.HTTP_200_OK

    def test_a_store_that_cannot_be_read_refuses_in_production(
        self, client, test_user, monkeypatch
    ):
        """Fail-closed, like every other check that can deny access.

        Answering "not revoked" because Redis is down hands a replayed
        session straight through, at the moment the system has already
        decided it is compromised.
        """
        access, _ = _login(client, test_user)
        monkeypatch.setattr(token_blacklist, '_redis', None)
        monkeypatch.setattr(type(token_blacklist), '_fail_closed', lambda self: True)

        assert _me(client, access).status_code == status.HTTP_401_UNAUTHORIZED
