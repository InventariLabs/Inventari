"""Custom ASGI middleware: body size limiting, language detection, performance
tracking, request ID correlation and the API key's deprecated Bearer form.

All of them are pure ASGI (not BaseHTTPMiddleware) to avoid the well-known
event-loop binding issues that BaseHTTPMiddleware exhibits with async SQLAlchemy
and asyncpg connections.
"""

import re
import time
from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core._request_id import generate_request_id, request_id_var
from app.core.contracts import API_KEY_HEADER, API_KEY_PREFIX
from app.core.datetimes import set_request_country
from app.core.performance import get_performance_stats, reset_query_count
from app.i18n.service import get_language_from_accept_header, set_current_lang


def _get_settings():
    from app.config import settings

    return settings


def _logger():
    from app.core.logging import get_logger

    return get_logger('app.middleware')


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before they are buffered.

    Endpoint-level size checks run after Starlette has already read the
    whole body into memory (or spooled it to disk), so they cap what gets
    processed, not what gets accepted. Behind the reverse proxy the
    Caddyfile stops that; a backend exposed directly had nothing.

    A declared ``Content-Length`` over the limit is refused without reading
    a single byte. Chunked bodies, which declare nothing, are counted as
    they arrive and cut off as soon as they cross the line.

    The refusal is written from the receive channel rather than raised
    through it. Raising is what a plain handler turns into a 413 and what
    Starlette's multipart parser turns into "There was an error parsing the
    body" with status 400 — so the same oversized upload got two different
    answers depending on whether it declared its length, and the chunked one
    told the client its request was malformed. Once the answer is sent, the
    application's own response is dropped: it is answering a request that was
    cut off underneath it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> Any:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        limit = getattr(_get_settings(), 'MAX_REQUEST_BODY_SIZE', 0)
        if limit <= 0:
            return await self.app(scope, receive, send)

        if self._declares_more_than(scope, limit):
            return await self._reject(send, scope)

        return await self._count_while_reading(scope, receive, send, limit)

    @staticmethod
    def _declares_more_than(scope: Scope, limit: int) -> bool:
        """True when ``Content-Length`` already says the body is too big.

        A malformed header says nothing, and the counting path below is what
        answers for it.
        """
        declared = dict(scope.get('headers', [])).get(b'content-length')
        if declared is None:
            return False
        try:
            return int(declared) > limit
        except ValueError:
            return False

    async def _count_while_reading(
        self, scope: Scope, receive: Receive, send: Send, limit: int
    ) -> Any:
        received = 0
        response_started = False
        refused = False

        async def limited_receive() -> MutableMapping[str, Any]:
            nonlocal received, refused
            if refused:
                return {'type': 'http.disconnect'}
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > limit:
                    refused = True
                    if not response_started:
                        await self._reject(send, scope)
                    # The body ended here as far as the application is
                    # concerned. It will unwind on its own; whatever it says
                    # about it goes nowhere, because the answer is already
                    # on the wire.
                    return {'type': 'http.disconnect'}
            return message

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal response_started
            if refused:
                return
            if message['type'] == 'http.response.start':
                response_started = True
            await send(message)

        try:
            return await self.app(scope, limited_receive, send_wrapper)
        except Exception:
            # Cutting the body off mid-read is visible to the application as
            # a disconnect, and what it raises about that varies by route —
            # ClientDisconnect from `request.body()`, a parse failure from
            # the multipart parser. Once the 413 is on the wire there is
            # nothing left to report, so the unwinding is swallowed. Any
            # other request's exception still travels.
            if not refused:
                raise
            return None

    async def _reject(self, send: Send, scope: Scope) -> None:
        _logger().warning(
            'Request body over the limit rejected: %s %s',
            scope.get('method', '?'),
            scope.get('path', '?'),
        )
        body = b'{"detail":"Request body too large"}'
        await send(
            {
                'type': 'http.response.start',
                'status': 413,
                'headers': [
                    (b'content-type', b'application/json'),
                    (b'content-length', str(len(body)).encode()),
                ],
            }
        )
        await send({'type': 'http.response.body', 'body': body})


class LanguageMiddleware:
    """Detect language from ``Accept-Language`` header and store it in contextvar.

    Modules read the language via :func:`get_current_lang` so error messages can
    be rendered in the user's preferred language.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> Any:
        if scope['type'] == 'http':
            headers = dict(scope.get('headers', []))
            # Latin-1 maps every byte, so a value outside UTF-8 is read as a
            # language tag nobody speaks, never a ``UnicodeDecodeError``.
            accept_language = headers.get(b'accept-language', b'').decode('latin-1')
            lang = get_language_from_accept_header(accept_language)
            set_current_lang(lang)
            # Known once the user is: see ``get_current_user``.
            set_request_country(None)
        return await self.app(scope, receive, send)


class PerformanceMiddleware:
    """Count DB queries, measure process time, and log per-request stats.

    In ``DEBUG`` mode the response is augmented with the following headers:
    - ``x-process-time`` — total request handling time in seconds
    - ``x-db-queries`` — number of SQL queries executed during the request
    - ``x-db-time`` — cumulative time spent in SQL queries (seconds)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> Any:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        reset_query_count()
        start_time = time.time()
        status_code = 500
        settings = _get_settings()

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message.get('status', 500)
                process_time = time.time() - start_time
                queries, db_time = get_performance_stats()

                if settings.DEBUG:
                    headers = list(message.get('headers', []))
                    headers.extend(
                        [
                            (b'x-process-time', f'{process_time:.3f}s'.encode()),
                            (b'x-db-queries', str(queries).encode()),
                            (b'x-db-time', f'{db_time:.3f}s'.encode()),
                        ]
                    )
                    message['headers'] = headers

                client_host = scope.get('client', ('unknown', 0))[0]
                method = scope.get('method', '?')
                path = scope.get('path', '?')
                _logger().info(
                    f'{client_host} - "{method} {path}" {status_code} '
                    f'[time:{process_time:.3f}s, queries:{queries}, db_time:{db_time:.3f}s]'
                )
            await send(message)

        return await self.app(scope, receive, send_with_headers)


class RequestIDMiddleware:
    """Generate or propagate an ``X-Request-ID`` for every request.

    A client's ``X-Request-ID`` is reused when it has the shape of an id —
    8 to 64 letters, digits and hyphens, which a UUID or a trace id has;
    otherwise, or when there is none, a new UUID4 is generated. The id is
    written verbatim into every log line of the request, so a space, a quote
    or a byte outside ASCII would let a client shape those lines, and a byte
    outside UTF-8 used to stop the request with a 500. The ID is:
    - stored in a contextvar (``request_id_var``) for log correlation
    - returned in the ``X-Request-ID`` response header
    """

    HEADER_NAME = b'x-request-id'
    _ACCEPTED_ID = re.compile(r'[0-9A-Za-z-]{8,64}')

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> Any:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        # Check for inbound X-Request-ID
        headers = dict(scope.get('headers', []))
        incoming = headers.get(self.HEADER_NAME, b'').decode('latin-1').strip()
        accepted = self._ACCEPTED_ID.fullmatch(incoming) is not None
        rid = incoming if accepted else generate_request_id()

        # Set contextvar for downstream log correlation
        token = request_id_var.set(rid)
        # And on the request itself, for the 500 handler: Starlette runs it
        # outside every middleware, after this one has reset the contextvar
        # and without passing its answer back through ``send_with_request_id``.
        scope.setdefault('state', {})['request_id'] = rid

        async def send_with_request_id(message: MutableMapping[str, Any]) -> None:
            if message['type'] == 'http.response.start':
                resp_headers = list(message.get('headers', []))
                resp_headers.append((self.HEADER_NAME, rid.encode()))
                message['headers'] = resp_headers
            await send(message)

        try:
            return await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)


class ApiKeyBearerDeprecationMiddleware:
    """Mark a response to an API key sent as ``Authorization: Bearer``.

    A key has its own header now; the Bearer form, which it shared with the
    session token, is honoured for one more minor release. Every answer to it
    — a refusal included — carries ``Deprecation`` (RFC 9745, dated from when
    the header arrived), so a client's maintainer finds what to change in any
    response they log.
    A request that also sends the key's own header is not marked: that is a
    client bridging old servers and new.
    """

    #: 2026-10-23T00:00:00Z, the day keys got their own header.
    DEPRECATED_SINCE = b'@1792713600'
    _BEARER_KEY = f'bearer {API_KEY_PREFIX}'.encode()
    _OWN_HEADER = API_KEY_HEADER.lower().encode()

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> Any:
        if scope['type'] != 'http' or not self._uses_bearer_form(scope):
            return await self.app(scope, receive, send)

        async def send_with_deprecation(message: MutableMapping[str, Any]) -> None:
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers.append((b'deprecation', self.DEPRECATED_SINCE))
                message['headers'] = headers
            await send(message)

        return await self.app(scope, receive, send_with_deprecation)

    def _uses_bearer_form(self, scope: Scope) -> bool:
        headers = dict(scope.get('headers', []))
        if self._OWN_HEADER in headers:
            return False
        return headers.get(b'authorization', b'').lower().startswith(self._BEARER_KEY)
