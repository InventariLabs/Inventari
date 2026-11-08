import asyncio
import json
import traceback
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_utils import maybe_await
from app.core.db_retry import mark_external_effect
from app.core.db_utils import transaction_scoped_info
from app.core.logging import get_logger
from app.core.posting_batch import current_batch

if TYPE_CHECKING:
    from redis.typing import EncodableT, FieldT

from app.config import settings
from app.core._event_deprecations import warn_if_deprecated
from app.core._event_types import (
    EventPayload,
    TenantEventPayload,
    _sa_json_default,
)
from app.core._redis_streams import prune_consumers, xautoclaim_messages
from app.core.contracts.events import (
    event_owner,
    get_payload_type,
    is_core_event,
    validate_event_payload,
)
from app.core.module_identity import (
    current_module,
    event_emission_refusal,
    module_scope,
)

logger = get_logger(__name__)

#: How long one handler may hold the consumer loop before it is abandoned.
#: The loop now waits for handlers before acknowledging, so an unbounded
#: handler would stall every later event on this node.
HANDLER_TIMEOUT_S = 30.0

#: How long ``disconnect`` waits for the loop to finish what it is holding
#: before cancelling it. Shorter than the handler bound on purpose: a
#: shutdown that waits out a stuck handler is a shutdown that hangs, and an
#: unacknowledged message is redelivered — which is the point of not
#: acknowledging early.
SHUTDOWN_DRAIN_S = 10.0

#: How many times one handler runs for one event before it is given up on:
#: the first delivery and four retries.
MAX_HANDLER_ATTEMPTS = 5

#: The wait before the first retry; it doubles with every attempt after
#: (30 s, 1 min, 2 min, 4 min), so a dependency down for a few minutes is
#: waited out and a handler that is simply broken is parked within ~8 min.
RETRY_BASE_DELAY_S = 30.0


def retry_delay(attempts: int) -> timedelta:
    """How long to wait before running a handler that failed *attempts* times."""
    return timedelta(seconds=RETRY_BASE_DELAY_S * 2 ** (attempts - 1))


def handler_name(callback: Callable[..., Any]) -> str:
    """``module.qualname`` of a function — how the delivery log names it."""
    module = getattr(callback, '__module__', '?')
    return f'{module}.{getattr(callback, "__qualname__", repr(callback))}'


def _organization_uuid(payload: EventPayload | None) -> uuid.UUID | None:
    """The payload's tenant as a UUID, or None when it has none it can parse.

    The stream carries whatever another node or version put in it; a
    tenant that is not a UUID still gets its failure recorded (the payload
    keeps the value), it just cannot be told to an organization's admins.
    """
    org_id = getattr(payload, 'organization_id', None)
    if not org_id:
        return None
    try:
        return uuid.UUID(str(org_id))
    except ValueError:
        return None


# Once-per-process flag for the no-Redis local-dispatch fallback warning.
_fallback_warned = False

# Once-per-name flags for the unregistered-event fail-open warning.
_unregistered_warned: set[str] = set()


# A rollback takes the TESTING buffer with it, as it takes the outbox row, and
# a savepoint's rollback only what was buffered inside it. Without this, events
# buffered by ``emit_transactional`` in a transaction that was then rolled back
# would be dispatched by the next ``flush_pending`` on the same session: an
# announcement of a write that never happened.
transaction_scoped_info('_pending_outbox_events')


def _warn_fallback_once() -> None:
    global _fallback_warned
    if not _fallback_warned:
        _fallback_warned = True
        logger.warning(
            '[EventBus] Redis stream unavailable — events are dispatched '
            'in-process only. Other nodes will NOT see them (fail-open).'
        )


def _payload_to_json_dict(payload: EventPayload) -> dict[str, Any]:
    """Normalize a payload to a JSON-safe dict (UUID/datetime → str)."""
    normalized: dict[str, Any] = json.loads(
        json.dumps(payload.model_dump(), default=_sa_json_default)
    )
    return normalized


def _validate_against_registry(event: str, payload: EventPayload) -> EventPayload:
    """Validate/coerce *payload* against the registered contract.

    One place, not emitter discipline: every emit — facade or raw — passes
    through here. Registered names are coerced to their contract type; a
    payload that fails validation raises ``EventValidationError`` at the
    emitter (fail-closed, same semantics as the ``core_api.events`` facade).
    Unregistered names fail open with a once-per-name warning, so custom
    module events keep flowing while the registry catches up.
    """
    payload_type = get_payload_type(event)
    if payload_type is None:
        if event not in _unregistered_warned:
            _unregistered_warned.add(event)
            logger.warning(
                '[EventBus] No payload contract registered for %s — '
                'emitting unvalidated (fail-open for one release).',
                event,
            )
        return payload
    if isinstance(payload, payload_type):
        return payload
    return validate_event_payload(event, payload.model_dump())


class EventBus:
    """
    Advanced asynchronous event bus for inter-module communication.

    Redis Streams carry the messages and a consumer group hands each one to
    exactly one worker. Delivery is **at-least-once**: the worker runs the
    handlers first and acknowledges after, so anything interrupted in
    between comes back through :meth:`reclaim_pending_events`.

    A handler that raises, or outlasts ``HANDLER_TIMEOUT_S``, does not end
    in a log line and an acknowledgement: it is written to the delivery log
    and the retry worker (``app.core.event_delivery_retry``) runs it again —
    that handler alone — up to ``MAX_HANDLER_ATTEMPTS`` times with doubling
    backoff, then parks it as ``dead`` and warns the organization's admins
    (the instance's superusers for an event of no organization).

    **The handler contract.** A handler may run more than once for the same
    event, so it must be idempotent: raise *before* its side effect, or make
    the side effect safe to repeat (look the effect up by the event's own
    ids before creating it). Handlers that succeeded are not re-run by a
    retry of a sibling that failed.
    """

    def __init__(self) -> None:
        self._listeners: dict[
            str, list[tuple[Callable[..., Any], int, str | None]]
        ] = {}

        self._redis: redis.Redis | None = None
        self._node_id = str(uuid.uuid4())
        self._stream_name = settings.REDIS_STREAM_NAME
        self._group_name = 'inventari_workers'
        self._listen_task: asyncio.Task[Any] | None = None
        #: What the delivery log calls each subscribed callback.
        self._handler_names: dict[Callable[..., Any], str] = {}
        #: The module a callback was subscribed by, captured at subscribe
        #: time — dispatch restores it so a handler running for module foo
        #: speaks for foo, wherever the event was emitted from. Core
        #: subscriptions carry None and no identity is bound.
        self._handler_modules: dict[Callable[..., Any], str | None] = {}
        #: Where the delivery log is written; None means the application's
        #: own session factory (tests point a bus at theirs).
        self._session_factory: Any = None
        #: Set by ``disconnect`` so the loop can finish the message it is
        #: holding instead of being cancelled inside a handler.
        self._stopping = False

    async def connect(self, redis_url: str) -> None:
        """Connect to Redis and ensure stream group exists."""
        try:
            self._redis = redis.from_url(redis_url, decode_responses=True)
            logger.info('[EventBus] Connected to Redis (Node: %s)', self._node_id)

            try:
                await self._redis.xgroup_create(
                    self._stream_name, self._group_name, id='0', mkstream=True
                )
            except redis.ResponseError as e:
                if 'BUSYGROUP' not in str(e):
                    raise

        except (RedisError, OSError) as e:
            logger.error('[EventBus] Failed to connect to Redis: %s', e)

    def subscribe(
        self,
        event: str,
        callback: Callable[[EventPayload], Any],
        priority: int = 100,
        *,
        org_filter: str | None = None,
        name: str | None = None,
    ) -> None:
        """Subscribe to a system event (local dispatch).

        ``org_filter``: when set, the listener is skipped for payloads
        whose ``organization_id`` does not match (or that carry no tenant) —
        enforced at dispatch time, in the consumer path.

        ``name``: what the delivery log calls this handler, when *callback*
        is a closure around the real one (the subscription helpers pass the
        wrapped function's name). Defaults to *callback*'s own.
        """
        self._handler_names[callback] = name or handler_name(callback)
        self._handler_modules[callback] = current_module()
        if event not in self._listeners:
            self._listeners[event] = []

        self._listeners[event].append((callback, priority, org_filter))
        self._listeners[event].sort(key=lambda x: x[1])

        event_name = str(event)
        logger.debug(
            '[EventBus] Subscribed to %s: %s (priority: %s)',
            event_name,
            callback.__name__,
            priority,
        )

    async def _safe_execute(
        self, callback: Callable[..., Any], **kwargs: Any
    ) -> str | None:
        """Run a callback; return what went wrong, or None when nothing did."""
        try:
            await maybe_await(callback, **kwargs)
        except Exception as e:  # noqa: BLE001 — failing event callbacks must never break the main flow
            logger.error(
                '[EventBus] Error in callback %s for event: %s', callback.__name__, e
            )
            logger.error(traceback.format_exc())
            return f'{type(e).__name__}: {e}'
        return None

    async def _run_handler(
        self, event: str, callback: Callable[..., Any], **kwargs: Any
    ) -> str | None:
        """One handler, bounded in time; returns its failure, or None.

        A handler that never returns would hold the consumer loop — and with
        it every later event — for as long as the process lives. Past the
        bound the handler is abandoned and the log says which one stopped
        answering; on a stream delivery that counts as a failure like any
        exception, so it is recorded and retried (see
        :meth:`_execute_local`). Halfway to the bound a warning names the
        handler while it is still running, because handlers run in sequence
        and one slow subscriber delays every later event on this node.
        """
        name = getattr(callback, '__name__', repr(callback))
        slow_warning = asyncio.get_running_loop().call_later(
            HANDLER_TIMEOUT_S / 2,
            logger.warning,
            '[EventBus] Handler %s for %s has been running for %ss (bound: '
            '%ss) — handlers run in sequence, so every later event on this '
            'node waits behind it',
            name,
            event,
            HANDLER_TIMEOUT_S / 2,
            HANDLER_TIMEOUT_S,
        )
        try:
            subscriber = self._handler_modules.get(callback)
            scope = module_scope(subscriber) if subscriber else nullcontext()
            with scope:
                return await asyncio.wait_for(
                    self._safe_execute(callback, **kwargs), HANDLER_TIMEOUT_S
                )
        except TimeoutError:
            logger.error(
                '[EventBus] Handler %s for %s exceeded %ss and was abandoned',
                name,
                event,
                HANDLER_TIMEOUT_S,
            )
            return f'Timed out after {HANDLER_TIMEOUT_S:g} s'
        finally:
            slow_warning.cancel()

    async def _execute_local(
        self,
        event: str,
        *,
        delivery_key: str | None = None,
        may_repeat: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Run every matching local listener to completion, in priority order.

        ``delivery_key`` is the event's identity on a stream delivery. With
        it, a handler that fails is not forgotten: it is written to the
        delivery log (:class:`~app.models.event_delivery.EventDelivery`),
        and the retry worker runs it again — alone — with backoff, until it
        succeeds or is parked as dead. ``may_repeat`` says the event may have
        been delivered before (a reclaim, or a relay that re-published its
        row); then a handler that already has a row is skipped, because it
        belongs to the worker now. A first delivery cannot have one, so it
        does not ask the database. Returns False when a failure
        could not be recorded, so the caller leaves the message pending
        rather than acknowledging a loss. Without a key (TESTING's inline
        dispatch, the no-Redis fallback) a failure is logged, as before.

        The caller is the consumer loop, and it acknowledges the stream
        message when this returns — so "to completion" is the whole point.
        This used to hand each handler to ``asyncio.create_task`` outside of
        tests and return immediately: the message was acknowledged before a
        single handler had run, a crash in the window between lost the event
        with no pending entry to reclaim, and the tasks were not even held in
        a reference, so the garbage collector was free to drop one mid-flight.

        Sequential, and the same in tests as in production. ``subscribe``
        takes a priority and sorts the listener list by it, which only means
        something if the handlers actually run in that order; firing them
        concurrently made the parameter decorative in production and honest
        in tests, which is the worst of both.
        """
        if event not in self._listeners:
            return True

        payload = kwargs.get('payload')
        payload_org = getattr(payload, 'organization_id', None)
        taken_over = (
            await self._handlers_with_a_delivery_row(delivery_key)
            if delivery_key and may_repeat
            else set()
        )
        settled = True
        for callback, _, org_filter in self._listeners[event]:
            if org_filter is not None and (
                payload_org is None or str(payload_org) != org_filter
            ):
                continue
            if self.name_of(callback) in taken_over:
                continue
            error = await self._run_handler(event, callback, **kwargs)
            if error is not None and delivery_key is not None:
                recorded = await self._record_failure(
                    delivery_key, event, callback, payload, error
                )
                settled = settled and recorded
        return settled

    def name_of(self, callback: Callable[..., Any]) -> str:
        """The delivery-log name of a subscribed *callback*."""
        return self._handler_names.get(callback) or handler_name(callback)

    def find_handler(
        self, event: str, name: str, organization_id: str | None
    ) -> Callable[..., Any] | None:
        """The subscribed callback called *name* that would take this event.

        The retry worker's lookup: the tenant filter still applies, so a
        handler scoped to one organization is never retried with another's
        event.
        """
        for callback, _, org_filter in self._listeners.get(event, []):
            if self.name_of(callback) != name:
                continue
            if org_filter is not None and org_filter != organization_id:
                continue
            return callback
        return None

    async def run_handler(
        self, event: str, callback: Callable[..., Any], payload: EventPayload
    ) -> str | None:
        """Run one handler, bounded; return its failure, or None."""
        return await self._run_handler(event, callback, payload=payload)

    def _sessions(self) -> Any:
        """The session factory the delivery log is written through."""
        if self._session_factory is not None:
            return self._session_factory
        from app.core import db_facade

        return db_facade.AsyncSessionLocal

    async def _handlers_with_a_delivery_row(self, delivery_key: str) -> set[str]:
        from sqlalchemy import select

        from app.models.event_delivery import EventDelivery

        factory = self._sessions()
        if factory is None:
            return set()
        try:
            async with factory() as db:
                rows = await db.execute(
                    select(EventDelivery.handler).where(
                        EventDelivery.event_id == delivery_key
                    )
                )
                return set(rows.scalars().all())
        except (SQLAlchemyError, OSError) as exc:
            logger.error('[EventBus] Could not read the delivery log: %s', exc)
            return set()

    async def _record_failure(
        self,
        delivery_key: str,
        event: str,
        callback: Callable[..., Any],
        payload: EventPayload | None,
        error: str,
    ) -> bool:
        """Write the failed handler to the delivery log for the retry worker.

        Returns False when the row could not be written: the caller then
        leaves the message unacknowledged, and reclaim brings the whole
        event back, rather than acknowledging a failure nobody recorded.
        """
        from sqlalchemy.dialects.postgresql import insert

        from app.models.event_delivery import EventDelivery

        factory = self._sessions()
        if factory is None:
            logger.error(
                '[EventBus] No database to record the failure of %s for %s',
                self.name_of(callback),
                event,
            )
            return True
        stmt = (
            insert(EventDelivery)
            .values(
                id=uuid.uuid4(),
                event_id=delivery_key,
                event=event,
                handler=self.name_of(callback),
                organization_id=_organization_uuid(payload),
                payload=_payload_to_json_dict(payload) if payload else {},
                status='retrying',
                attempts=1,
                last_error=error,
                next_attempt_at=datetime.now(UTC) + retry_delay(1),
            )
            .on_conflict_do_nothing(constraint='uq_event_deliveries_event_handler')
        )
        try:
            # Its own session, so its own transaction: nothing of a caller's
            # rides on it, and begin() commits it on the way out.
            async with factory() as db, db.begin():
                await db.execute(stmt)
        except (SQLAlchemyError, OSError, ValueError) as exc:
            logger.error(
                '[EventBus] Could not record the failure of %s for %s: %s',
                self.name_of(callback),
                event,
                exc,
            )
            return False
        return True

    async def emit(self, event: str, payload: EventPayload) -> None:
        """
        Emit an event.

        Semantics:
        - **Production (Redis connected)**: stream-only — ``emit`` performs a
          single XADD and returns. The message is delivered to exactly one
          consumer-group worker (possibly this node), which runs the handlers
          and only then acknowledges. Local immediate execution was removed
          because it double-fired handlers with N > 1 workers.
        - **TESTING**: inline local dispatch, no stream (hundreds of tests
          depend on synchronous handler execution).
        - **No Redis / Redis failure**: fail-open local dispatch with a
          once-per-process warning; other nodes miss the event.

        **What is guaranteed, and what is not.** Handlers run *at least*
        once, not exactly once: a worker that dies after running a handler
        but before the ACK leaves the message pending, and the next
        ``reclaim_pending_events`` runs the handlers again. Handlers must
        therefore tolerate being re-run. (This docstring used to say
        "exactly once" while the consumer acknowledged before dispatching at
        all, which made the real guarantee *at most* once — the opposite
        error, and the expensive one.)

        A handler that fails — an exception, or outlasting
        ``HANDLER_TIMEOUT_S`` — is retried from the delivery log with
        backoff and, when it keeps failing, parked as dead with an alert to
        the admins. Only stream deliveries are retried: the TESTING inline
        dispatch and the no-Redis fallback still just log the failure.

        Two edges the delivery does not cover, by construction:

        - ``emit`` itself is not transactional. It is an XADD after your
          commit, so a crash in between loses the event, and an emit before
          a rollback announces something that did not happen. Where the
          event must agree with the transaction, use
          :meth:`emit_transactional`, which writes to the outbox in the same
          transaction and lets the relay publish it.
        - The stream is capped at ``EVENT_STREAM_MAXLEN``. A consumer that
          is offline long enough for its backlog to be trimmed does not get
          those events, and nothing reports that they were dropped.
        """
        # This XADD (or the inline TESTING dispatch below) is an external
        # effect the surrounding rollback cannot undo, so a request whose
        # transaction later hits a deadlock must not be retried past this
        # point. ``emit_transactional`` does not mark: its event only leaves
        # the database after the commit succeeds.
        mark_external_effect(f'event-bus:emit:{event}')
        event_value = str(event)
        warn_if_deprecated(event_value)
        self._refuse_foreign_event(event_value)
        payload = _validate_against_registry(event_value, payload)
        logger.info('[EventBus] Emitting event: %s', event_value)

        if self._redis and not settings.TESTING:
            try:
                message_data: dict[FieldT, EncodableT] = {
                    'event': event_value,
                    # The event's identity in the delivery log, the same on
                    # every redelivery of this message.
                    'event_id': uuid.uuid4().hex,
                    'sender_id': self._node_id,
                    # Who emitted it, when a module did. The sender is a node
                    # UUID, which attributes nothing to a module: the first
                    # buggy community module to emit under a name it did not
                    # own left a failure nobody could trace back to it.
                    'module': current_module() or '',
                    'payload': json.dumps(
                        payload.model_dump(), default=_sa_json_default
                    ),
                }
                await self._redis.xadd(
                    self._stream_name,
                    message_data,
                    maxlen=settings.EVENT_STREAM_MAXLEN,
                    approximate=True,
                )
                return
            except (RedisError, OSError, ValueError) as e:
                logger.error('[EventBus] Failed to XADD to Redis: %s', e)
                _warn_fallback_once()
        elif not settings.TESTING:
            _warn_fallback_once()

        await self._execute_local(event, payload=payload)

    async def emit_transactional(
        self, db: AsyncSession, event: str, payload: EventPayload
    ) -> None:
        """Persist the event to the outbox in the CALLER'S transaction.

        The row is published to the Redis stream by the outbox relay only
        AFTER the surrounding commit, so a crash between commit and publish
        can no longer lose the event. Use this for state-changing business
        operations; plain ``emit()`` remains for non-transactional paths.

        Callers must NOT commit before calling this — the outbox row rides
        along with the business commit (rollback drops the event too, which
        is exactly the desired semantics). After committing, callers should
        call :meth:`flush_pending` — a no-op in production, where the relay
        picks the row up asynchronously.

        TESTING keeps the legacy synchronous semantics: the event is buffered
        on the session and dispatched inline by ``flush_pending`` AFTER the
        commit, so handlers reading committed state from their own sessions
        behave exactly as with the old post-commit ``emit()``.
        """
        event_value = str(event)
        warn_if_deprecated(event_value)
        self._refuse_foreign_event(event_value)
        payload = _validate_against_registry(event_value, payload)

        if settings.TESTING:
            pending = db.info.setdefault('_pending_outbox_events', [])
            pending.append((event_value, payload))
            return

        from app.models.event_outbox import EventOutbox

        org_id = getattr(payload, 'organization_id', None)
        row = EventOutbox(
            organization_id=uuid.UUID(str(org_id)) if org_id else None,
            event=event_value,
            payload=_payload_to_json_dict(payload),
            emitter_module=current_module(),
        )
        batch = current_batch(db)
        if batch is not None:
            # Written with the posting's other appended rows, before its commit.
            row.id = uuid.uuid4()
            batch.add(row)
            return
        db.add(row)
        await db.flush()

    def _refuse_foreign_event(self, event_name: str) -> None:
        """Refuse an emit into a namespace the current module does not own."""
        if current_module() is None:
            return
        from app.core.module_registry import module_registry

        refusal = event_emission_refusal(
            event_name,
            core_owned=is_core_event(event_name),
            runtime_owner=event_owner(event_name),
            known_modules={
                module.metadata.name for module in module_registry.get_all()
            },
        )
        if refusal is not None:
            raise ValueError(refusal)

    async def flush_pending(self, db: AsyncSession) -> None:
        """Dispatch events buffered by :meth:`emit_transactional` in TESTING.

        Production is a no-op (the outbox relay handles publishing); the
        buffered list is always cleared so a session can be reused safely.
        Call AFTER the surrounding ``db.commit()``.
        """
        pending: list[tuple[str, EventPayload]] = db.info.pop(
            '_pending_outbox_events', []
        )
        if not pending or not settings.TESTING:
            return
        for event, payload in pending:
            await self.emit(event, payload)

    async def listen(self) -> None:
        """Main loop: Listen for Stream events."""
        if not self._redis:
            return

        logger.info(
            '[EventBus] Listening for Stream events (Node: %s)...',
            self._node_id,
        )

        async def listen_stream() -> None:
            last_id = '>'
            while not self._stopping:
                try:
                    assert self._redis is not None
                    streams = await self._redis.xreadgroup(
                        self._group_name,
                        self._node_id,
                        {self._stream_name: last_id},
                        count=10,
                        block=1000,
                    )
                    if not streams:
                        continue

                    for _stream, messages in streams:  # type: ignore[str-unpack]
                        for msg_id, data in messages:  # type: ignore[str-unpack,union-attr]
                            # The ACK comes after the handlers, not after the
                            # dispatch call returns. Until it does, the
                            # message stays in this consumer's pending list,
                            # so a crash here is a redelivery rather than a
                            # loss -- reclaim_pending_events is what brings
                            # it back.
                            settled = await self._handle_stream_message(msg_id, data)  # type: ignore[arg-type]
                            if settled:
                                await self._redis.xack(
                                    self._stream_name, self._group_name, msg_id
                                )
                except asyncio.CancelledError:
                    break
                except (RedisError, OSError, ValueError) as e:
                    logger.error('[EventBus] Stream listen error: %s', e)
                    await asyncio.sleep(1)

        await listen_stream()

    async def _handle_stream_message(
        self, msg_id: str, data: dict[str, Any], *, redelivered: bool = False
    ) -> bool:
        """Processes a message from Redis Stream; True when it may be ACKed.

        False only when a handler failed and the failure could not be written
        to the delivery log: the message then stays pending, and reclaim
        delivers the event again instead of the failure being lost.

        The consumer group delivers each message to exactly one consumer, so
        the sender's own messages are handled too — stream-only emit
        makes this the ONLY execution path, and skipping sender_id could
        leave an event unhandled when the sender is the sole live consumer.

        Events are dispatched by their plain string name: custom
        module events outside ``SystemEvent`` must flow too (namespacing),
        so unknown names are dispatched to whoever subscribed them.
        """
        event_name = data.get('event')
        payload_json = data.get('payload', '{}')

        payload: EventPayload | TenantEventPayload
        try:
            payload_data = json.loads(payload_json)
            if 'organization_id' in payload_data:
                payload = TenantEventPayload(**payload_data)
            else:
                payload = EventPayload(**payload_data)
        except (json.JSONDecodeError, ValidationError) as exc:
            # Poison, not a hiccup. The caller acknowledges only after this
            # returns and reclaim redelivers anything left pending, so a
            # payload that cannot be parsed would come back on every reclaim
            # for as long as the installation runs -- and no number of
            # retries will make it parse. Dropped here, loudly: the contract
            # is checked when an event is emitted, and this is the far side
            # of that, where the sender may be another node or another
            # version and is no longer under our control.
            logger.error(
                '[EventBus] Discarding unparseable payload for %s (%s): %s',
                event_name,
                msg_id,
                exc,
            )
            return True

        try:
            if event_name:
                # Messages from before the id was carried fall back to the
                # stream id, which is stable across reclaims too.
                return await self._execute_local(
                    str(event_name),
                    payload=payload,
                    delivery_key=str(data.get('event_id') or msg_id),
                    # The relay re-publishes a row whose commit it did not
                    # see, so its messages can repeat as well.
                    may_repeat=redelivered or data.get('sender_id') == 'outbox-relay',
                )
            logger.warning('[EventBus] Stream message without event name: %s', msg_id)
        except (RedisError, OSError) as e:
            logger.error('[EventBus] Error processing stream message %s: %s', msg_id, e)
        return True

    async def reclaim_pending_events(
        self, min_idle_ms: int | None = None, count: int = 100
    ) -> int:
        """XAUTOCLAIM stale pending entries to this node and process them.

        Pending entries are messages a consumer read but never ACKed (e.g.
        it crashed mid-handler). Without reclaim they would never be
        retried. Returns the number of reclaimed + processed messages.
        """
        if not self._redis:
            return 0
        idle = min_idle_ms if min_idle_ms is not None else settings.STREAM_CLAIM_IDLE_MS
        messages = await xautoclaim_messages(
            self._redis,
            self._stream_name,
            self._group_name,
            self._node_id,
            idle,
            count=count,
            label='EventBus',
        )

        reclaimed = 0
        for msg_id, data in messages:
            if data:
                reclaimed += 1
                if not await self._handle_stream_message(
                    msg_id, data, redelivered=True
                ):
                    continue  # still unrecorded — left pending for the next reclaim
            # Empty data = entry trimmed from the stream; ACK drops the
            # dangling pending reference either way.
            await self._redis.xack(self._stream_name, self._group_name, msg_id)
        if reclaimed:
            logger.info('[EventBus] Reclaimed %d pending event(s)', reclaimed)
        return reclaimed

    async def prune_dead_consumers(self, min_idle_ms: int) -> int:
        """Remove the group's idle, empty-handed consumers other than this one."""
        if not self._redis:
            return 0
        return await prune_consumers(
            self._redis,
            self._stream_name,
            self._group_name,
            min_idle_ms=min_idle_ms,
            keep=self._node_id,
            label='EventBus',
        )

    async def disconnect(self) -> None:
        """Graceful shutdown: let the loop finish, then close Redis.

        Cancelling outright was safe while handlers ran in detached tasks —
        nothing was waiting on them, and nothing was keeping them alive
        either. Now the loop holds an unacknowledged message while its
        handlers run, so cancelling it mid-handler would abandon work that
        the ACK was going to vouch for. It is asked to stop, and given
        ``SHUTDOWN_DRAIN_S`` to reach the top of its loop.

        A handler that outlasts that window is cancelled, and the message it
        was holding stays unacknowledged — the next node to reclaim it runs
        the handlers again. A shutdown that waits indefinitely for one stuck
        handler is a deployment that does not finish.
        """
        self._stopping = True
        if self._listen_task and not self._listen_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._listen_task), SHUTDOWN_DRAIN_S
                )
            except TimeoutError:
                logger.warning(
                    '[EventBus] Handlers still running after %ss — cancelling',
                    SHUTDOWN_DRAIN_S,
                )
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
        if self._redis:
            # Leave the group tidily: this process's name is never used again.
            # A consumer still holding a cancelled message stays, so the
            # reclaim can find it.
            await prune_consumers(
                self._redis,
                self._stream_name,
                self._group_name,
                min_idle_ms=0,
                only=self._node_id,
                label='EventBus',
            )
            await self._redis.aclose()
            self._redis = None
        self._stopping = False

    async def start_listener(self) -> None:
        """Start the background listener task (safe to call from lifespan)."""
        self._stopping = False
        self._listen_task = asyncio.create_task(self.listen())

    @property
    def is_listening(self) -> bool:
        """Whether the EventBus background listener is active."""
        return self._listen_task is not None and not self._listen_task.done()

    @property
    def is_connected(self) -> bool:
        """Whether the EventBus has an active Redis connection."""
        return self._redis is not None

    @property
    def redis(self) -> redis.Redis | None:
        """The underlying Redis client (for shared use by core services only)."""
        return self._redis

    @property
    def stream_name(self) -> str:
        """The Redis stream events are published to (core services only)."""
        return self._stream_name


event_bus = EventBus()
