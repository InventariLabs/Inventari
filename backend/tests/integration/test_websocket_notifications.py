"""Integration tests for the WS-driven notification pipeline.

The NotificationHub at app/api/websocket.py accepts ``/ws/notifications``
with the access token offered as a subprotocol (``bearer, <jwt>``) and
forwards Redis Pub/Sub messages to the authenticated user's connected
clients. The producer side lives in
``core_api.notifications.publish_async``, which modules call AFTER their
own ``db.commit()`` so subscribers see the row before being notified.

These tests cover:
  * Token blacklist / blocked / inactive users are refused on connect.
  * The WS room is the authenticated user id; a client cannot
          impersonate another user via query params.
  * Producer contract — ``publish_async`` publishes on ``notifications:user:{id}``
          and never leaks between users.
"""

import asyncio
import json
import uuid as _uuid_mod
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.websocket import hub
from app.core.events import event_bus
from app.core.public_api import core_api
from app.core.token_blacklist import token_blacklist
from app.services.token_service import create_access_token
from tests.integration._fake_token_store import FakeTokenStore

# `uuid` is already used as a function name (`uuid.uuid4`) inside the test
# bodies below; importing the stdlib module under that name shadows the
# function. Use the module alias for clarity.
uuid = _uuid_mod.uuid4


WS_URL = '/api/v1/ws/notifications'


def _ws_token(test_user) -> str:
    return create_access_token(data={'sub': str(test_user.id)})


def _bearer(token: str) -> list[str]:
    """What the browser offers: the marker, then the token, as subprotocols."""
    return ['bearer', token]


@pytest.mark.integration
class TestWebSocketEndpoint:
    """The /ws/notifications endpoint accepts a JWT and registers the
    socket in the NotificationHub under the user's id."""

    def test_ws_connects_with_valid_token(self, client: TestClient, test_user) -> None:
        token = _ws_token(test_user)
        user_id = str(test_user.id)
        baseline = len(hub._connections.get(user_id, set()))
        with client.websocket_connect(WS_URL, subprotocols=_bearer(token)) as socket:
            assert len(hub._connections.get(user_id, set())) > baseline
            # A browser that offered subprotocols drops a socket whose server
            # picks none, so the server has to answer with the marker.
            assert socket.accepted_subprotocol == 'bearer'

    def test_ws_does_not_read_a_token_from_the_address(
        self, client: TestClient, test_user
    ) -> None:
        """A token in the query string lands in every access log on the way.

        The socket used to take it there; a client that still does is refused,
        so the address never becomes a way in again.
        """
        from starlette.websockets import WebSocketDisconnect

        token = _ws_token(test_user)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f'{WS_URL}?token={token}'):
                pass
        assert exc_info.value.code == 4001

    def test_ws_rejects_missing_token(self, client: TestClient) -> None:
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(WS_URL):
                pass
        assert exc_info.value.code == 4001

    def test_ws_rejects_blacklisted_token(self, client: TestClient, test_user) -> None:
        """A token that has been revoked on logout must close with 4001."""
        from starlette.websockets import WebSocketDisconnect

        token = _ws_token(test_user)

        fake = FakeTokenStore()
        original_redis = token_blacklist._redis
        token_blacklist.set_redis(fake)  # type: ignore[arg-type]

        async def _revoke() -> None:
            await token_blacklist.revoke(
                token, datetime.now(tz=UTC) + timedelta(minutes=5)
            )

        try:
            asyncio.run(_revoke())
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(WS_URL, subprotocols=_bearer(token)):
                    pass
            assert exc_info.value.code == 4001
            assert 'revoked' in str(exc_info.value.reason or '').lower()
        finally:
            token_blacklist._redis = original_redis

    def test_ws_rejects_blocked_user(
        self, client: TestClient, async_test_user, monkeypatch
    ) -> None:
        """A blocked user must close with 4003."""
        from starlette.websockets import WebSocketDisconnect

        from app.api import websocket as ws_module

        async def _stub_blocked(user_id):  # type: ignore[no-untyped-def]
            return (
                async_test_user.id,
                async_test_user.organization_id,
                True,
            )

        monkeypatch.setattr(ws_module, 'resolve_notification_user', _stub_blocked)

        token = _ws_token(async_test_user)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(WS_URL, subprotocols=_bearer(token)):
                pass
        assert exc_info.value.code == 4003
        assert 'blocked' in str(exc_info.value.reason or '').lower()

    def test_ws_rejects_inactive_user(
        self, client: TestClient, async_test_user, monkeypatch
    ) -> None:
        """An inactive user must close with 4001."""
        from starlette.websockets import WebSocketDisconnect

        from app.api import websocket as ws_module

        async def _stub_inactive(user_id):  # type: ignore[no-untyped-def]
            return (None, None, False)

        monkeypatch.setattr(ws_module, 'resolve_notification_user', _stub_inactive)

        token = _ws_token(async_test_user)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(WS_URL, subprotocols=_bearer(token)):
                pass
        assert exc_info.value.code == 4001


@pytest.mark.integration
@pytest.mark.asyncio
class TestNotificationHubBroadcastUnit:
    """Unit-level coverage of NotificationHub.broadcast and listen_redis routing.

    The hub is keyed by user id (not organization) — each delivery must reach
    only the socket registered for that user.
    """

    async def test_broadcast_no_connections_is_noop(self) -> None:
        from app.api.websocket import NotificationHub

        local_hub = NotificationHub()
        await local_hub.broadcast('nonexistent-user', {'x': 1})

    async def test_broadcast_delivers_only_to_target_user(self) -> None:
        """A user-targeted message must not leak to other users' sockets."""
        from app.api.websocket import NotificationHub

        local_hub = NotificationHub()

        class _FakeWS:
            def __init__(self) -> None:
                self.received: list[dict] = []
                self.closed = False

            async def accept(self, subprotocol: str | None = None) -> None:
                pass

            async def send_json(self, payload: dict) -> None:
                self.received.append(payload)

            async def close(self) -> None:
                self.closed = True

        target = _FakeWS()
        bystander = _FakeWS()

        await local_hub.connect(target, 'user-target')  # type: ignore[arg-type]
        await local_hub.connect(bystander, 'user-other')  # type: ignore[arg-type]
        await local_hub.broadcast('user-target', {'hello': 'world'})

        assert target.received == [{'hello': 'world'}]
        assert bystander.received == []

    async def test_broadcast_marks_dead_socket_and_skips(self) -> None:
        from app.api.websocket import NotificationHub

        local_hub = NotificationHub()

        class _DeadWS:
            async def accept(self, subprotocol: str | None = None) -> None:
                pass

            async def send_json(self, payload: dict) -> None:
                raise RuntimeError('connection lost')

            async def close(self) -> None:
                pass

        class _LiveWS:
            def __init__(self) -> None:
                self.received: list[dict] = []

            async def accept(self, subprotocol: str | None = None) -> None:
                pass

            async def send_json(self, payload: dict) -> None:
                self.received.append(payload)

            async def close(self) -> None:
                pass

        dead = _DeadWS()
        live = _LiveWS()

        await local_hub.connect(dead, 'user-x')  # type: ignore[arg-type]
        await local_hub.connect(live, 'user-x')  # type: ignore[arg-type]
        await local_hub.broadcast('user-x', {'ping': 1})

        assert live.received == [{'ping': 1}]
        assert (
            'user-x' not in local_hub._connections
            or dead not in local_hub._connections.get('user-x', set())
        )


@pytest.mark.integration
@pytest.mark.asyncio
class TestNotificationPublisherContract:
    """``core_api.notifications.publish_async`` publishes on the per-user
    channel ``notifications:user:{user_id}`` and never on the org channel."""

    async def test_publish_called_with_user_channel(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        published: list[tuple[str, str]] = []

        class _FakeRedis:
            async def publish(self, channel: str, payload: str) -> int:
                published.append((channel, payload))
                return 1

        original_redis = event_bus.redis
        event_bus._redis = _FakeRedis()  # type: ignore[assignment]
        try:
            notification = await core_api.notifications.create_async(
                real_async_db_session,
                async_test_user.id,
                title='WS test',
                content='hello',
                notification_type='info',
                link='/x',
            )
            await real_async_db_session.commit()
            await core_api.notifications.publish_async(
                real_async_db_session, notification
            )
        finally:
            event_bus._redis = original_redis

        assert notification is not None
        assert len(published) == 1, 'expected exactly one Redis publish'
        channel, raw = published[0]
        assert channel == f'notifications:user:{async_test_user.id}'
        body = json.loads(raw)
        assert body['title'] == 'WS test'
        assert body['content'] == 'hello'
        assert body['user_id'] == str(async_test_user.id)
        assert body['id'] == str(notification.id)
        assert async_test_user.organization_id is not None
