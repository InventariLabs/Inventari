"""Central retry for serialization failures and deadlocks.

The database answers a deadlock (SQLSTATE ``40P01``) or a serialization
conflict (``40001``) by killing the transaction, and before this module
that answer went straight to the client as a 500. The architecture keeps
concurrency conflicts out with careful locks (ADR-020 and its siblings),
but no lock discipline can exclude two paths that lock the same rows in
opposite orders — for those, the caller has to try again. Odoo retries
every RPC up to five times on exactly these two codes; this is the same
net under the paths the locks do not cover.

The retry is a pure ASGI middleware, not a route wrapper, because the
route tree is no longer walkable: since FastAPI 0.141 an
``include_router`` parks a lazy ``_IncludedRouter`` in the parent and
materialises its own route copies at match time, so touching the
original route objects covers nothing that was included. The middleware
sees every request the app sees, whatever the router does underneath.

Retrying a request is only safe when the failed transaction had no
effects the rollback cannot undo: a mail already sent, a webhook already
delivered, a file already written, an LLM already billed, an event
already published to the stream. Outbox rows are exempt — they only
leave the database after the commit succeeds, so a rolled-back attempt
never publishes them. That rule is enforced by mechanism, not by
convention: the choke points that perform external effects
(:meth:`EventBus.emit`, the email entry points, the file-storage writes,
the LLM clients, webhook delivery) call :func:`mark_external_effect`,
and the middleware below refuses a replay once anything has marked the
attempt. Nothing marks it, the transaction rolls back whole, and the
replay is indistinguishable from a first attempt.

The replay re-enters only the app: one request keeps one request id, one
rate-limit count and one performance record, and the outer middlewares
build their headers once. Two further gates, both mechanical:

* **A started response.** The replay only ever happens before the first
  byte; once ``http.response.start`` left, the caller holds half an
  answer and the failure stands.
* **A replayable body.** The body is recorded as the first attempt reads
  it, under a byte cap from settings — an upload is never buffered just
  so it could be retried, and what is not buffered cannot be replayed.
  A handler that never read the body leaves the original channel
  intact, and the retry takes it as is.
"""

from __future__ import annotations

import asyncio
import random
from contextvars import ContextVar
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = get_logger(__name__)

#: The only two error codes worth a retry. Everything else — constraint
#: violations, connection loss, syntax — either cannot succeed on a second
#: attempt or must not be papered over here.
RETRYABLE_SQLSTATES = frozenset({'40001', '40P01'})

#: Response header naming how many attempts a retried request took. Present
#: only when a retry actually happened, so a normal response carries nothing.
RETRY_ATTEMPTS_HEADER = 'x-db-retry-attempts'

#: Indirection for tests: the backoff must be observable without waiting.
_sleep = asyncio.sleep


def sqlstate_of(exc: BaseException) -> str | None:
    """The SQLSTATE of *exc*, found through the wrapper chain.

    SQLAlchemy wraps the driver's error twice over (``DBAPIError`` around
    the asyncpg ``PostgresError``), and the driver hides the code under
    ``sqlstate`` where psycopg calls it ``pgcode`` — both names are read,
    on every link of the chain, because where the chain stops depends on
    which layer raised. An exception whose ``orig``/``__cause__`` points back
    at an earlier link ends the walk instead of spinning the event loop.
    """
    seen: BaseException | None = exc
    visited: set[int] = set()
    while seen is not None and id(seen) not in visited:
        visited.add(id(seen))
        code = getattr(seen, 'sqlstate', None) or getattr(seen, 'pgcode', None)
        if isinstance(code, str):
            return code
        seen = getattr(seen, 'orig', None) or seen.__cause__
    return None


class _RetryState:
    """One attempt's view of what must keep it from being repeated.

    ``tainted`` is the decision the middleware makes; ``taint_reason`` is
    the evidence it logs when the answer is no.
    """

    __slots__ = ('taint_reason',)

    def __init__(self) -> None:
        self.taint_reason: str | None = None

    @property
    def tainted(self) -> bool:
        return self.taint_reason is not None


_retry_state: ContextVar[_RetryState | None] = ContextVar(
    'inventari_db_retry_state', default=None
)


def mark_external_effect(reason: str) -> None:
    """Say that the running request has done something a rollback cannot undo.

    Called from the choke points that perform external effects (mail,
    webhook/event publication, file storage, LLM calls). Outside a retried
    request — in a worker, a script, a plain test — there is no state to
    mark and this is a no-op. Inside a thread the context was copied into,
    the mark still lands: contexts are copied by reference to the state
    object, so a mutation is seen by whoever awaits the thread.
    """
    state = _retry_state.get()
    if state is not None and not state.tainted:
        state.taint_reason = reason


def _retry_delay_seconds(attempt: int) -> float:
    """Backoff for the *attempt*-th retry, with jitter.

    Linear backoff plus uniform jitter: two colliding requests should not
    meet again at the same instant, which is what a fixed sleep would
    arrange. The scale is milliseconds — Postgres already made the first
    contender wait out its ``deadlock_timeout`` before reporting, so the
    collision is over by the time the rollback finishes.
    """
    from app.config import settings

    backoff = settings.DB_RETRY_BACKOFF_MS / 1000 * attempt
    jitter = random.uniform(0, settings.DB_RETRY_JITTER_MS / 1000)
    return backoff + jitter


class _RequestBody:
    """The request body, read once and replayed to every attempt.

    The first attempt reads through :meth:`live`, which records what goes
    by; later attempts read from :meth:`replay`. Recording stops being
    worth it past the byte cap — an upload is not buffered just so it
    could be retried — and a body the handler never touched leaves the
    original channel untouched, which the retry reuses instead.
    """

    def __init__(self, receive: Receive, cap: int) -> None:
        self._receive = receive
        self._cap = cap
        self._messages: list[Message] = []
        self._bytes_seen = 0
        self._consumed_any = False
        self._complete = False
        self._unreplayable = False

    def live(self) -> Receive:
        """A channel that records the body as the first attempt reads it."""

        async def _receive() -> Message:
            message = await self._receive()
            if message['type'] == 'http.request':
                self._consumed_any = True
                self._bytes_seen += len(message.get('body', b''))
                if self._bytes_seen > self._cap:
                    # The cap does not just refuse the replay — it stops
                    # the recording: an upload is never buffered (past the
                    # capped prefix) just so it could be retried. The body
                    # itself still flows to the handler unchanged.
                    self._unreplayable = True
                else:
                    self._messages.append(message)
                if not message.get('more_body', False):
                    self._complete = True
            elif message['type'] == 'http.disconnect':
                self._unreplayable = True
            return message

        return _receive

    def replay(self) -> Receive:
        """A channel that serves the recorded body to a later attempt."""
        cursor = 0

        async def _receive() -> Message:
            nonlocal cursor
            if cursor < len(self._messages):
                message = self._messages[cursor]
                cursor += 1
                return message
            return {'type': 'http.disconnect'}

        return _receive

    def channel_for(self, attempt: int) -> Receive:
        if attempt == 1:
            return self.live()
        if not self._consumed_any:
            # Nothing was read; the original channel still holds the body.
            return self._receive
        return self.replay()

    @property
    def replayable(self) -> bool:
        if self._unreplayable:
            return False
        # A partially read body cannot be reconstructed: the unread part is
        # still upstream of us, and there is no second copy of the read one.
        return self._complete or not self._consumed_any


class TransactionRetryMiddleware:
    """Replays a request the database aborted with 40001/40P01.

    Registered in ``app.main`` right outside the body-size gate: what it
    buffers has already passed that gate, and its own byte cap is far
    below it. Inside the decorators (CORS, security headers, the
    performance log) on purpose: a replay re-enters only the app, so one
    request keeps one request id, one rate-limit count and one
    performance record, and the headers a response carries are built
    once.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        from app.config import settings

        max_attempts = max(1, settings.DB_RETRY_MAX_ATTEMPTS)
        body = _RequestBody(receive, settings.DB_RETRY_MAX_BODY_BYTES)

        response_started = False
        attempts_used = 0

        async def _guarded_send(message: Message) -> None:
            nonlocal response_started
            if message['type'] == 'http.response.start':
                response_started = True
                if attempts_used > 1:
                    header = RETRY_ATTEMPTS_HEADER.encode()
                    message['headers'] = [
                        *message.get('headers', []),
                        (
                            header,
                            str(attempts_used).encode(),
                        ),
                    ]
            await send(message)

        attempt = 0
        while True:
            attempt += 1
            attempts_used = attempt
            state = _RetryState()
            token = _retry_state.set(state)
            try:
                await self.app(scope, body.channel_for(attempt), _guarded_send)
                return
            except Exception as exc:  # retried by SQLSTATE, anything else re-raised
                code = sqlstate_of(exc)
                retryable = (
                    code in RETRYABLE_SQLSTATES
                    and attempt < max_attempts
                    and not state.tainted
                    and not response_started
                    and body.replayable
                )
                if not retryable:
                    if (
                        code in RETRYABLE_SQLSTATES
                        and attempt < max_attempts
                        and state.tainted
                    ):
                        logger.warning(
                            '[DbRetry] Not retrying %s %s after %s: external '
                            'effect before the failure (%s)',
                            scope.get('method', '?'),
                            scope.get('path', '?'),
                            code,
                            state.taint_reason,
                        )
                    raise
                delay = _retry_delay_seconds(attempt)
                logger.warning(
                    '[DbRetry] %s on %s %s (attempt %d/%d); replaying in %.0f ms',
                    code,
                    scope.get('method', '?'),
                    scope.get('path', '?'),
                    attempt,
                    max_attempts,
                    delay * 1000,
                )
                await _sleep(delay)
            finally:
                _retry_state.reset(token)
