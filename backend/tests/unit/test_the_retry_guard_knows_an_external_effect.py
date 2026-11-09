"""The retry guard knows an external effect when it sees one.

A request whose transaction dies in a deadlock (SQLSTATE 40P01) or a
serialization conflict (40001) is retried by ``app.core.db_retry`` — but
only when nothing has left a trace the rollback cannot undo. That rule is
a mechanism, not a convention: the choke points that perform external
effects (event publication, mail, file storage, LLM calls) mark the
running attempt on their way out, and the wrapper refuses to repeat a
marked one. These tests pin the marking and the decision; the refusal
against a real deadlock lives in the integration test beside the
choreography that produces it.
"""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import httpx
from fastapi import Request

from app.core import db_retry
from app.core._event_bus import EventBus
from app.core.contracts.events import EventPayload
from app.core.db_retry import mark_external_effect, sqlstate_of
from app.core.file_storage.schemas import StorageConfigSchema
from app.core.file_storage.service import FileStorageService
from app.services.email_service import EmailService


@contextmanager
def _attempt_state():
    """Install a retry state the way the route wrapper does for one attempt."""
    state = db_retry._RetryState()
    token = db_retry._retry_state.set(state)
    try:
        yield state
    finally:
        db_retry._retry_state.reset(token)


class _FakeDeadlockError(Exception):
    pgcode = '40P01'


class _FakeSerializationError(Exception):
    sqlstate = '40001'


def test_sqlstate_is_found_through_wrapper_chains():
    """SQLAlchemy wraps the driver error twice; both names are read, on any link."""
    inner = _FakeDeadlockError()
    middle = ValueError('sqlalchemy wrap')
    middle.orig = inner
    outer = ValueError('handler wrap')
    outer.__cause__ = middle
    assert sqlstate_of(outer) == '40P01'
    assert sqlstate_of(_FakeSerializationError()) == '40001'
    assert sqlstate_of(ValueError('nothing db-ish')) is None


def test_a_mark_outside_a_request_is_a_noop():
    """Workers and scripts call the same choke points; there is nothing to guard."""
    mark_external_effect('unit-test')
    assert db_retry._retry_state.get() is None


async def test_a_bare_emit_marks_the_attempt():
    """A direct ``emit`` publishes (or dispatches inline) before any commit."""
    bus = EventBus()
    with _attempt_state() as state:
        await bus.emit('db_retry.probe', EventPayload())
        assert state.tainted
        assert state.taint_reason is not None


async def test_a_transactional_emit_does_not_mark():
    """The outbox row only leaves the database after the commit succeeds."""
    bus = EventBus()
    db = SimpleNamespace(info={})  # emit_transactional only buffers on it in TESTING
    with _attempt_state() as state:
        await bus.emit_transactional(db, 'db_retry.probe', EventPayload())
        assert not state.tainted


async def test_a_queued_email_marks_the_attempt():
    """Both email paths outlive the rollback: the SMTP send, and the queue row."""
    with _attempt_state() as state:
        # Unconfigured SMTP makes the TESTING path fail fast — the mark is
        # set before the send is attempted either way.
        await EmailService.send_email_async('nobody@localhost', 's', '<p>x</p>')
        assert state.tainted


async def test_a_file_storage_write_and_delete_mark_the_attempt(tmp_path):
    previous_provider = FileStorageService._provider
    try:
        FileStorageService.initialize(
            StorageConfigSchema(backend='local', local_path=str(tmp_path))
        )
        with _attempt_state() as state:
            await FileStorageService().save('probe.txt', BytesIO(b'x'))
            assert state.tainted
        with _attempt_state() as state:
            await FileStorageService().delete('probe.txt')
            assert state.tainted
    finally:
        FileStorageService._provider = previous_provider


async def test_an_llm_call_marks_the_attempt(stub_dns):
    """The provider is billed the moment the call is made, not at commit."""
    from app.core.llm.base import LlmRequest
    from app.core.llm.openai_client import OpenAiCompatibleClient
    from app.models.ai_connection import AiConnection

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'choices': [{'message': {'content': 'pong'}}]})

    conn = AiConnection(
        organization_id=UUID('00000000-0000-0000-0000-000000000001'),
        name='test',
        provider='openai',
        api_key_enc='sk-test',
        api_base_url='https://openrouter.ai/api/v1',
        model_name='gemini-2.0-flash',
    )
    client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
    with _attempt_state() as state:
        await client.complete(LlmRequest(prompt='ping'))
        assert state.tainted


async def test_the_wrapper_retries_and_reports_the_attempt_count():
    """A retryable SQLSTATE gets the attempts the settings allow, then a header."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    calls = {'n': 0}

    async def endpoint() -> dict:
        calls['n'] += 1
        if calls['n'] == 1:
            raise _FakeDeadlockError()
        return {'ok': True}

    app = FastAPI()
    app.get('/probe')(endpoint)
    app.add_middleware(db_retry.TransactionRetryMiddleware)

    async with AsyncClient(transport=ASGITransport(app=app)) as ac:
        response = await ac.get('http://t/probe')

    assert response.status_code == 200
    assert response.json() == {'ok': True}
    assert calls['n'] == 2
    assert response.headers[db_retry.RETRY_ATTEMPTS_HEADER] == '2'


async def test_the_wrapper_does_not_retry_what_is_not_a_sqlstate():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    calls = {'n': 0}

    async def endpoint() -> dict:
        calls['n'] += 1
        raise ValueError('not a database answer')

    app = FastAPI()
    app.get('/probe')(endpoint)
    app.add_middleware(db_retry.TransactionRetryMiddleware)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False)
    ) as ac:
        response = await ac.get('http://t/probe')

    assert response.status_code == 500
    assert calls['n'] == 1


async def test_the_wrapper_refuses_a_marked_attempt():
    """The mechanism, not a convention: one external effect, no retry."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    calls = {'n': 0}

    async def endpoint() -> dict:
        calls['n'] += 1
        mark_external_effect('unit-test:email')
        raise _FakeDeadlockError()

    app = FastAPI()
    app.get('/probe')(endpoint)
    app.add_middleware(db_retry.TransactionRetryMiddleware)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False)
    ) as ac:
        response = await ac.get('http://t/probe')

    assert response.status_code == 500
    assert calls['n'] == 1
    assert db_retry.RETRY_ATTEMPTS_HEADER not in response.headers


async def test_the_body_recording_stops_at_the_cap():
    """The cap is a memory bound, not just a flag: past it, nothing is kept.

    An upload the handler reads must flow through unchanged — but it is
    never buffered whole just so it could be retried. What was recorded
    before the cap was crossed stays (bounded by the cap), the crossing
    message and everything after it is passed on and dropped.
    """
    incoming = [
        {'type': 'http.request', 'body': b'12345678', 'more_body': True},
        {'type': 'http.request', 'body': b'9012345678901234', 'more_body': True},
        {'type': 'http.request', 'body': b'more', 'more_body': False},
    ]
    queue = list(incoming)

    async def receive() -> dict:
        return queue.pop(0)

    body = db_retry._RequestBody(receive, cap=10)
    channel = body.live()

    seen = [await channel() for _ in incoming]

    # The handler still sees every byte, in order, untouched.
    assert seen == incoming
    # The recording stopped where the cap was crossed: the first message
    # (8 bytes, under the cap) is kept, the crossing one and the tail are not.
    assert body._messages == [incoming[0]]
    assert body._bytes_seen == 8 + 16 + 4
    assert not body.replayable


async def test_the_wrapper_does_not_replay_an_over_cap_body(monkeypatch):
    """A request too big to buffer is not retried on a retryable SQLSTATE.

    Pins the refusal, which held before the cap stopped the recording too
    (the mechanism test above is the one that discriminates); it stays
    because the middleware decision — not the buffer — is what the client
    sees.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.config import settings

    monkeypatch.setattr(settings, 'DB_RETRY_MAX_BODY_BYTES', 8)

    calls = {'n': 0}

    async def endpoint(request: Request) -> dict:
        calls['n'] += 1
        await request.body()  # read it all, the way an upload handler would
        raise _FakeDeadlockError()

    app = FastAPI()
    app.post('/probe')(endpoint)
    app.add_middleware(db_retry.TransactionRetryMiddleware)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False)
    ) as ac:
        response = await ac.post('http://t/probe', content=b'x' * 32)

    assert response.status_code == 500
    assert calls['n'] == 1
    assert db_retry.RETRY_ATTEMPTS_HEADER not in response.headers
