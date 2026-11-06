"""A header value outside UTF-8 is read as a header that says nothing.

HTTP lets a header value carry any byte above 0x7F, and the server hands the
bytes on as they came. ``RequestIDMiddleware`` and ``LanguageMiddleware``
decoded theirs as UTF-8, so one such byte in ``X-Request-ID`` or
``Accept-Language`` raised ``UnicodeDecodeError`` before the request reached
a route: the client met a 500 for a header that only names a log line or
chooses the language of the answer.

The ASGI app is called directly: the test client re-encodes header values on
the way in, so the bytes the server would pass never arrive through it.
"""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from typing import Any

import pytest

from app._middleware import LanguageMiddleware, RequestIDMiddleware
from app.core._request_id import get_request_id
from app.i18n.service import get_current_lang, get_default_language


def _send_raw(middleware: type, header: bytes, value: bytes) -> dict[str, Any]:
    """One GET through *middleware* carrying *header* as raw bytes."""
    seen: dict[str, Any] = {}

    async def endpoint(scope: Any, receive: Any, send: Any) -> None:
        seen['request_id'] = get_request_id()
        seen['lang'] = get_current_lang()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/',
        'headers': [(header, value)],
    }
    asyncio.run(middleware(endpoint)(scope, receive, send))
    seen['status'] = sent[0]['status']
    seen['headers'] = dict(sent[0].get('headers', []))
    return seen


@pytest.mark.unit
def test_a_request_id_outside_utf8_is_replaced_by_one_of_the_servers_own() -> None:
    seen = _send_raw(RequestIDMiddleware, b'x-request-id', b'\xff\xfeabcdefgh')

    assert seen['status'] == 200
    rid = seen['headers'][b'x-request-id'].decode()
    assert len(rid) == 32  # generated, UUID4 hex
    assert seen['request_id'] == rid


@pytest.mark.unit
def test_a_language_header_outside_utf8_falls_back_to_the_default() -> None:
    seen = _send_raw(LanguageMiddleware, b'accept-language', b'\xffpl')

    assert seen['status'] == 200
    assert seen['lang'] == get_default_language()


@pytest.mark.unit
def test_a_readable_language_header_still_chooses_the_language() -> None:
    seen = _send_raw(LanguageMiddleware, b'accept-language', b'pl-PL,pl;q=0.9')

    assert seen['lang'] == 'pl'
