"""Oversized request bodies are refused before a handler sees them.

Endpoint-level checks run after Starlette has buffered the whole body, so
they bound what gets processed rather than what gets accepted. Behind the
reverse proxy the Caddyfile caps this; a directly exposed backend did not.

This is the only limit that acts on the *input*, and the tests below say so
in the two shapes a client can send: a declared ``Content-Length`` is refused
without reading a byte, and a chunked body is cut while it arrives. The
per-file caps at the endpoints bound the copy that reaches memory, which is a
different promise — see ``test_upload_validation_limits.py`` for the copy
and ``test_a_per_file_limit_is_reachable.py`` for the relationship between
the two.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, File, Request, UploadFile
from httpx import ASGITransport, AsyncClient

from app._middleware import BodySizeLimitMiddleware
from app.config import settings

LIMIT = 1024


@pytest.fixture
def counting_app(monkeypatch):
    """An app that records how much of the body actually reached it.

    The question these tests exist to answer is not "was it refused" — the
    others cover that — but "how much arrived first". A cap that measures
    after the fact refuses just as loudly, having already taken the bytes.
    """
    monkeypatch.setattr(settings, 'MAX_REQUEST_BODY_SIZE', LIMIT)
    seen: dict[str, int] = {'calls': 0, 'bytes': 0}

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)

    @app.post('/echo')
    async def echo(request: Request):  # pragma: no cover - exercised via client
        seen['calls'] += 1
        async for chunk in request.stream():
            seen['bytes'] += len(chunk)
        return {'received': seen['bytes']}

    client = AsyncClient(transport=ASGITransport(app=app), base_url='http://test')
    return client, seen


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, 'MAX_REQUEST_BODY_SIZE', LIMIT)

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)
    return _build_app(app)


@pytest.fixture
def form_client(monkeypatch):
    """The same middleware over an endpoint that parses multipart — the
    path where an overflow surfaces mid-parse, inside request.form()."""
    monkeypatch.setattr(settings, 'MAX_REQUEST_BODY_SIZE', LIMIT)

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)
    return _build_app(app, multipart=True)


def _build_app(app: FastAPI, *, multipart: bool = False):
    handler_ran = {'flag': False}

    if multipart:
        # Declared as a body parameter, so FastAPI itself parses the
        # multipart body — the phase where an exception from the receive
        # channel gets wrapped into a 400 "error parsing the body". The
        # imports live at module level on purpose: a type local to this
        # function stays an unresolvable forward reference, and the first
        # request that actually reaches validation dies in pydantic before
        # the handler is ever called.

        @app.post('/upload')
        async def upload(file: UploadFile = File(...)):
            handler_ran['flag'] = True
            return {'received': len(await file.read())}

    else:

        @app.post('/echo')
        async def echo(request: Request):  # pragma: no cover - exercised via client
            handler_ran['flag'] = True
            body = await request.body()
            return {'received': len(body)}

    app.state.handler_ran = handler_ran
    return AsyncClient(transport=ASGITransport(app=app), base_url='http://test')


class TestBodySizeLimit:
    @pytest.mark.asyncio
    async def test_body_under_the_limit_passes(self, client):
        response = await client.post('/echo', content=b'x' * 100)

        assert response.status_code == 200
        assert response.json() == {'received': 100}

    @pytest.mark.asyncio
    async def test_declared_oversize_is_refused(self, client):
        response = await client.post('/echo', content=b'x' * (LIMIT + 1))

        assert response.status_code == 413
        assert 'too large' in response.json()['detail'].lower()

    @pytest.mark.asyncio
    async def test_body_exactly_at_the_limit_passes(self, client):
        response = await client.post('/echo', content=b'x' * LIMIT)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_chunked_body_is_counted_as_it_arrives(self, client):
        """No Content-Length to check, so the bytes have to be tallied."""

        async def chunks() -> AsyncIterator[bytes]:
            for _ in range(4):
                yield b'x' * 512

        response = await client.post('/echo', content=chunks())

        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_a_disabled_limit_lets_everything_through(self, monkeypatch, client):
        monkeypatch.setattr(settings, 'MAX_REQUEST_BODY_SIZE', 0)

        response = await client.post('/echo', content=b'x' * (LIMIT * 4))

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_the_handler_never_sees_a_refused_body(self, monkeypatch):
        """What separates this refusal from an endpoint-level one: the
        declared size is answered before a handler exists to receive a
        byte of the body."""
        monkeypatch.setattr(settings, 'MAX_REQUEST_BODY_SIZE', LIMIT)
        app = FastAPI()
        app.add_middleware(BodySizeLimitMiddleware)
        ran = {'flag': False}

        @app.post('/echo')
        async def echo(request: Request):
            ran['flag'] = True
            return {'received': len(await request.body())}

        client = AsyncClient(transport=ASGITransport(app=app), base_url='http://test')
        response = await client.post(
            '/echo',
            content=b'x' * (LIMIT + 1),
            headers={'Content-Length': str(LIMIT + 1)},
        )

        assert response.status_code == 413
        assert ran['flag'] is False

    @pytest.mark.asyncio
    async def test_a_chunked_multipart_over_the_limit_answers_413(self, form_client):
        """The overflow surfaces mid-parse, inside request.form(), where
        FastAPI re-raises anything it catches as a 400 'error parsing the
        body'. The 413 must survive that wrap."""

        async def chunks() -> AsyncIterator[bytes]:
            boundary = 'X-BOUNDARY'
            yield f'--{boundary}\r\n'.encode()
            yield (
                b'Content-Disposition: form-data; name="file"; '
                b'filename="big.bin"\r\n\r\n'
            )
            for _ in range(4):
                yield b'x' * 512
            yield f'\r\n--{boundary}--\r\n'.encode()

        response = await form_client.post(
            '/upload',
            content=chunks(),
            headers={'Content-Type': 'multipart/form-data; boundary=X-BOUNDARY'},
        )

        assert response.status_code == 413, response.text
        assert 'parsing the body' not in response.text
        assert form_client._transport.app.state.handler_ran['flag'] is False

    @pytest.mark.asyncio
    async def test_get_requests_are_untouched(self, client):
        response = await client.post('/echo', content=b'')

        assert response.status_code == 200


def _multipart(payload: bytes) -> bytes:
    boundary = b'----inventaritest'
    return (
        b'--' + boundary + b'\r\n'
        b'Content-Disposition: form-data; name="file"; filename="big.bin"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n' + payload + b'\r\n'
        b'--' + boundary + b'--\r\n'
    )


MULTIPART_HEADERS = {'Content-Type': 'multipart/form-data; boundary=----inventaritest'}


class TestWhereTheCutHappens:
    """Not "was it refused", but "how much had arrived by then"."""

    @pytest.mark.asyncio
    async def test_a_declared_oversize_never_reaches_the_handler(self, counting_app):
        client, seen = counting_app

        response = await client.post('/echo', content=b'x' * (LIMIT * 4))

        assert response.status_code == 413
        assert seen['calls'] == 0
        assert seen['bytes'] == 0

    @pytest.mark.asyncio
    async def test_a_chunked_body_is_cut_before_all_of_it_arrives(self, counting_app):
        client, seen = counting_app
        chunk_size = 512
        sent = 0

        async def chunks() -> AsyncIterator[bytes]:
            nonlocal sent
            for _ in range(40):
                sent += chunk_size
                yield b'x' * chunk_size

        response = await client.post('/echo', content=chunks())

        assert response.status_code == 413
        # The handler saw at most the limit plus the chunk that crossed it —
        # not the twenty kilobytes the client was willing to send.
        assert seen['bytes'] <= LIMIT + chunk_size
        assert sent <= LIMIT + chunk_size

    @pytest.mark.asyncio
    async def test_a_declared_multipart_over_the_limit_is_refused_the_same_way(
        self, form_client
    ):
        response = await form_client.post(
            '/upload', content=_multipart(b'x' * (LIMIT * 4)), headers=MULTIPART_HEADERS
        )

        assert response.status_code == 413
        assert form_client._transport.app.state.handler_ran['flag'] is False

    @pytest.mark.asyncio
    async def test_a_chunked_multipart_inside_the_limit_still_arrives(
        self, form_client
    ):
        """The positive control for the chunked refusals: chunking alone is
        not what gets a body cut — the size is."""
        body = _multipart(b'x' * 64)

        async def chunks() -> AsyncIterator[bytes]:
            for start in range(0, len(body), 32):
                yield body[start : start + 32]

        response = await form_client.post(
            '/upload', content=chunks(), headers=MULTIPART_HEADERS
        )

        assert response.status_code == 200, response.text
        assert form_client._transport.app.state.handler_ran['flag'] is True
