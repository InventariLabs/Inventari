import asyncio
import json

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import settings
from app.core.logging import get_logger
from app.core.token_blacklist import token_blacklist
from app.services.identity_service import resolve_notification_user

logger = get_logger(__name__)

router = APIRouter()

USER_CHANNEL_PREFIX = 'notifications:user:'

#: How often an open socket re-asks whether its credential is still good.
#: The handler used to authorise once, at connect, so a session revoked while
#: the socket was open kept receiving notifications until the client happened
#: to disconnect — which for a notification socket is "until the tab closes".
REVALIDATE_EVERY_SECONDS = 30.0


class NotificationHub:
    """Manages WebSocket connections + Redis Pub/Sub for real-time notifications.

    Rooms are keyed by user id so each delivery is scoped to a single recipient
    (no cross-user leak). The hub subscribes to ``notifications:user:*`` and
    forwards each message to every socket registered for the matching user.
    """

    def __init__(self) -> None:
        self._redis: Redis | None = None
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect_redis(self) -> None:
        self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def disconnect_redis(self) -> None:
        if self._redis:
            await self._redis.close()

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]

    async def broadcast(self, user_id: str, data: dict) -> None:
        """Push a message to all WebSocket connections for a user."""
        if user_id not in self._connections:
            return
        dead: list[WebSocket] = []
        for ws in self._connections[user_id]:
            try:
                await ws.send_json(data)
            except Exception:  # noqa: BLE001 — WebSocket send may fail on disconnected clients; must not crash the broadcast loop
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, user_id)

    async def listen_redis(self) -> None:
        """Listen for Redis Pub/Sub messages and broadcast to WebSocket clients."""
        if not self._redis:
            return
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(f'{USER_CHANNEL_PREFIX}*')
        try:
            async for message in pubsub.listen():
                if message['type'] != 'pmessage':
                    continue
                channel = message['channel']
                if not channel.startswith(USER_CHANNEL_PREFIX):
                    continue
                user_id = channel[len(USER_CHANNEL_PREFIX) :]
                try:
                    data = json.loads(message['data'])
                except (json.JSONDecodeError, TypeError):
                    data = {'message': str(message.get('data', ''))}
                await self.broadcast(user_id, data)
        except asyncio.CancelledError:
            pass
        except RedisConnectionError:
            # Shutdown closes the Redis connection while listen() is blocked
            # — a normal exit path, not an error worth a traceback.
            logger.info('[NotificationHub] Redis connection closed; listener stopped.')
        finally:
            try:
                await pubsub.punsubscribe()
                await pubsub.close()
            except Exception:  # noqa: BLE001 — cleanup must never raise during shutdown
                pass


hub = NotificationHub()


async def _credential_is_live(token: str, payload: dict) -> bool:
    """Everything the HTTP paths ask of an access token, asked here too.

    The socket checked the per-token blacklist and nothing else, so it missed
    both markers the HTTP flow honours: the credential-change one (a token
    minted before a password reset opened a socket the reset was supposed to
    have ended) and the session family (reuse detection and logout).
    """
    if await token_blacklist.is_revoked(token):
        return False

    user_id = str(payload.get('sub') or '')
    if not user_id:
        return False

    if await token_blacklist.is_issued_before_credential_change(
        user_id, payload.get('iat')
    ):
        return False

    return not await token_blacklist.is_user_revoked(
        user_id, str(payload.get('sid') or '')
    )


async def _close_when_credential_dies(
    websocket: WebSocket, token: str, payload: dict
) -> None:
    """Close the socket once its credential stops being good.

    Closing from here makes the reader's ``receive_text()`` raise, which
    unwinds the handler and deregisters the socket — no second copy of the
    teardown, and no cancelling a receive that is mid-flight.
    """
    while True:
        await asyncio.sleep(REVALIDATE_EVERY_SECONDS)
        if await _credential_is_live(token, payload):
            continue
        logger.info('WS: closing a socket whose credential was revoked.')
        try:
            await websocket.close(code=4001, reason='Token revoked')
        except RuntimeError:
            # Already closing from the other side; nothing left to do.
            pass
        return


@router.websocket('/ws/notifications')
async def notifications_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time notifications.

    The access token travels in the query string, which means it can land in
    proxy access logs and browser history — a known trade-off, kept because the
    browser WebSocket API cannot set an ``Authorization`` header and the
    alternative (smuggling the token through ``Sec-WebSocket-Protocol``) is
    awkward on both ends. It is bounded: the token is short-lived, the room is
    the authenticated user's own, and a leaked entry expires with the token.
    Reverse proxies in front of this endpoint should keep query strings out of
    their access logs.

    Query params:
        token   — required JWT access token.
        org_id  — ignored; the WS room is always the authenticated user's id,
                  derived server-side from the user record (a client-supplied
                  org_id must not let a user join another user's room).

    Close codes:
        4001 — missing/invalid token, token revoked, or user record invalid.
        4003 — user is blocked.
    """
    token = websocket.query_params.get('token', '')
    if not token:
        await websocket.close(code=4001, reason='Missing token')
        return

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id_claim: str | None = payload.get('sub')
        if not user_id_claim:
            await websocket.close(code=4001, reason='Invalid token')
            return
        # The socket takes an access token, not a long-lived refresh one.
        if payload.get('type') != 'access':
            await websocket.close(code=4001, reason='Invalid token')
            return
    except jwt.PyJWTError:
        await websocket.close(code=4001, reason='Invalid token')
        return

    # Enforce token revocation (logout) on the WebSocket too: the HTTP
    # JWT path checks the blacklist, but the WS handler only decoded the JWT,
    # so a logged-out user could keep an open notification socket otherwise.
    if not await _credential_is_live(token, payload):
        await websocket.close(code=4001, reason='Token revoked')
        return

    # Resolve the authoritative user from the user record instead of trusting
    # the client-supplied org_id query param. Done via a service helper so the
    # API layer never imports app.models / app.database directly, and the
    # session is short-lived (not held for the WS connection lifetime). The
    # helper also reports is_blocked so the WS can refuse blocked users.
    resolved_user_id, organization_id, is_blocked = await resolve_notification_user(
        user_id_claim
    )
    if resolved_user_id is None:
        await websocket.close(code=4001, reason='Invalid user')
        return

    if organization_id is None:
        await websocket.close(code=4001, reason='User has no organization')
        return

    # resolve_notification_user already rejects inactive users; also enforce
    # is_blocked here so a blocked-but-still-active user cannot subscribe.
    if is_blocked:
        await websocket.close(code=4003, reason='User blocked')
        return

    user_id = str(resolved_user_id)

    await hub.connect(websocket, user_id)
    watchdog = asyncio.create_task(
        _close_when_credential_dies(websocket, token, payload)
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        watchdog.cancel()
        await hub.disconnect(websocket, user_id)
