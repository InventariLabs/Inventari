from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_BASE_HEADERS: list[tuple[bytes, bytes]] = [
    (b'x-content-type-options', b'nosniff'),
    (b'x-frame-options', b'DENY'),
    (b'x-xss-protection', b'0'),
    (b'referrer-policy', b'strict-origin-when-cross-origin'),
    (b'permissions-policy', b'camera=(), microphone=(), geolocation=()'),
    (
        b'content-security-policy',
        b"default-src 'self'; script-src 'self'; style-src 'self'; "
        b"img-src 'self' data: blob:; font-src 'self'; frame-ancestors 'none'",
    ),
]
# HSTS deliberately absent: TLS terminates at Caddy, and that is where the
# policy rides — on every response the site serves, not just the API's. A
# second source here would be a second place the same commitment can drift.


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that injects security headers.

    Does NOT use BaseHTTPMiddleware to avoid event-loop issues with
    SQLAlchemy async engine connections.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> Any:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def send_with_headers(
            message: MutableMapping[str, Any],
        ) -> None:
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers.extend(_BASE_HEADERS)
                message['headers'] = headers
            await send(message)

        return await self.app(scope, receive, send_with_headers)
