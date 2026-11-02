"""A socket that opened once must not stay open on a dead credential.

The WebSocket handler decoded the token and checked the per-token blacklist,
which left two gaps. It never read the credential-change marker, so a token
minted before a password reset still opened a notification socket — the HTTP
paths have refused that since the reset work landed. And it authorised once,
at connect: a session revoked while the socket was open went on receiving
notifications until the client happened to disconnect.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import websocket as ws_module
from app.core.token_blacklist import token_blacklist
from app.services.token_service import create_access_token
from tests.integration._fake_token_store import FakeTokenStore

WS_URL = '/api/v1/ws/notifications'


@pytest.fixture
def blacklist_on() -> Any:
    previous = token_blacklist._redis  # noqa: SLF001
    fake = FakeTokenStore()
    token_blacklist.set_redis(fake)
    yield fake
    token_blacklist._redis = previous  # noqa: SLF001


def _token(user, **claims: Any) -> str:
    return create_access_token(data={'sub': str(user.id), **claims})


def _mark_credentials_changed(fake, user_id: str) -> None:
    fake.store[f'{token_blacklist.PREFIX}credchg:{user_id}'] = str(
        datetime.now(tz=UTC).timestamp()
    )


def _revoke_family(fake, user_id: str, session_id: str) -> None:
    fake.store[f'{token_blacklist.PREFIX}user:{user_id}:{session_id}'] = '1'


@pytest.mark.integration
class TestTheSocketRefusesADeadCredential:
    def test_a_token_from_before_a_password_reset_is_refused(
        self, client: TestClient, blacklist_on, test_user
    ) -> None:
        token = _token(test_user)
        _mark_credentials_changed(blacklist_on, str(test_user.id))

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f'{WS_URL}?token={token}'):
                pass

        assert exc.value.code == 4001

    def test_a_token_of_a_revoked_family_is_refused(
        self, client: TestClient, blacklist_on, test_user
    ) -> None:
        token = _token(test_user, sid='session-a')
        _revoke_family(blacklist_on, str(test_user.id), 'session-a')

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f'{WS_URL}?token={token}'):
                pass

        assert exc.value.code == 4001

    def test_a_live_token_still_connects(
        self, client: TestClient, blacklist_on, test_user
    ) -> None:
        token = _token(test_user, sid='session-ok')
        user_id = str(test_user.id)
        baseline = len(ws_module.hub._connections.get(user_id, set()))

        with client.websocket_connect(f'{WS_URL}?token={token}'):
            assert len(ws_module.hub._connections.get(user_id, set())) > baseline


@pytest.mark.integration
class TestTheSocketRechecksWhileItIsOpen:
    def test_a_family_revoked_after_connect_closes_the_socket(
        self, client: TestClient, blacklist_on, test_user, monkeypatch
    ) -> None:
        monkeypatch.setattr(ws_module, 'REVALIDATE_EVERY_SECONDS', 0.2)
        token = _token(test_user, sid='session-b')

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f'{WS_URL}?token={token}') as socket:
                _revoke_family(blacklist_on, str(test_user.id), 'session-b')
                socket.receive_text()

        assert exc.value.code == 4001

    def test_a_live_session_stays_open(
        self, client: TestClient, blacklist_on, test_user, monkeypatch
    ) -> None:
        monkeypatch.setattr(ws_module, 'REVALIDATE_EVERY_SECONDS', 0.05)
        token = _token(test_user, sid='session-c')
        user_id = str(test_user.id)

        with client.websocket_connect(f'{WS_URL}?token={token}'):
            time.sleep(0.3)
            assert ws_module.hub._connections.get(user_id)
