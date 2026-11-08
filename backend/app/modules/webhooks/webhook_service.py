"""Core webhook dispatch service.

Single-delivery mechanics live in _webhook_delivery, retry/cleanup workers
in _webhook_workers, and constants/payload builders in _webhook_constants.
This module keeps the public dispatch entry-point, the test-ping helper and
the secret-encryption helper.
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db_facade
from app.core.async_utils import await_if_awaitable
from app.core.events import SystemEvent, TenantEventPayload
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint

from ._module_gate import announces_own_switch_off, webhooks_enabled_async
from ._webhook_constants import (
    _DELIVERY_STATUS_FAILED,
    _DELIVERY_STATUS_PENDING,
    _DELIVERY_STATUS_PENDING_RETRY,
    _DELIVERY_STATUS_SUCCESS,
    MODULE_NAME,
    _serialize_payload,
    build_outbound_payload,
    event_name,
    wire_body,
)
from ._webhook_delivery import (
    _attempt_delivery,
    _breaker_threshold_async,
    _calc_next_retry,
    _update_stats_after_delivery,
)

MASKED_VALUE = core_api.secrets.MASKED

logger = get_logger(__name__)


async def _execute(db: AsyncSession, stmt: Any) -> Any:
    return await await_if_awaitable(db.execute(stmt))


async def count_endpoints_that_would_resume(
    db: AsyncSession, organization_id: UUID
) -> int:
    """Saved endpoints that start receiving the moment the module is switched on.

    Only the active ones: a paused or breaker-disabled endpoint stays quiet
    after the switch-on, and counting it would promise a send that never comes.
    """
    stmt = (
        select(func.count())
        .select_from(WebhookEndpoint)
        .where(
            WebhookEndpoint.organization_id == organization_id,
            WebhookEndpoint.is_active.is_(True),
        )
    )
    return int((await _execute(db, stmt)).scalar_one())


async def _flush(db: AsyncSession) -> None:
    await await_if_awaitable(db.flush())


def encrypt_secret(plain: str) -> str:
    """Encrypt a webhook signing secret, bound to this module.

    The secret belongs to an organization's endpoint and is read by this
    module alone, so it is a module secret and binds like one — the
    deprecated ``core_api.secrets.encrypt`` bound nothing, which made the
    stored text readable as any module's secret.
    """
    return core_api.secrets.encrypt_for_module(MODULE_NAME, plain)


# ---------------------------------------------------------------------------
# Main dispatch entry-point (called from event handler)
# ---------------------------------------------------------------------------


async def dispatch_event(
    event: SystemEvent | str,
    payload: TenantEventPayload,
) -> None:
    """Dispatch *event* to all matching active webhook endpoints for the org.

    The subscriber owns its transactions: it opens its own sessions through
    the module DB facade and closes them itself. It takes no caller's session
    — a subscriber that rode the request session closed the caller's unit of
    work from the inside, and a signature that accepts a session invites
    that shape back.
    """
    organization_id = (
        payload.organization_id
        if isinstance(payload.organization_id, UUID)
        else UUID(str(payload.organization_id))
    )

    async with db_facade.AsyncSessionLocal() as session:
        # One scope per durability boundary. This one commits the PENDING
        # rows BEFORE any HTTP attempt: a crash/restart mid-delivery then
        # leaves a durable row the retry worker requeues — the first attempt
        # is no longer fire-and-forget.
        async with session.begin():
            # Switched off means the outside world stops hearing — not that
            # the panel disappears while the sending carries on. The single
            # thing it still says is that it went off, so a listener can tell
            # that from an endpoint that is merely quiet.
            if not await webhooks_enabled_async(
                session, organization_id
            ) and not announces_own_switch_off(event_name(event), payload):
                return

            stmt = (
                select(WebhookEndpoint)
                .where(
                    WebhookEndpoint.organization_id == organization_id,
                    WebhookEndpoint.is_active.is_(True),
                )
                # Lock the matched rows for the short pending-insert
                # transaction: delivery stats are mutated from this read
                # later in the dispatch.
                .with_for_update()
            )
            endpoints = (await _execute(session, stmt)).scalars().all()

            # Filter by event type (JSONB contains check done in Python to
            # remain DB-agnostic)
            name = event_name(event)
            matching = [wh for wh in endpoints if name in (wh.event_types or [])]

            if not matching:
                return

            outbound = _serialize_payload(build_outbound_payload(event, payload))

            # Each endpoint gets its own copy of the payload carrying ITS
            # delivery id: the id is minted once with the delivery row, so
            # every attempt of that delivery — first probe here, retries in
            # the worker — sends the same header and the same body id, and a
            # receiver can dedup instead of double-applying.
            probes: list[tuple[WebhookEndpoint, bytes, dict[str, Any], str]] = []
            pending_logs: dict[UUID, WebhookDeliveryLog] = {}
            for wh in matching:
                delivery_id = str(uuid4())
                endpoint_payload = {**outbound, 'delivery_id': delivery_id}
                log = WebhookDeliveryLog(
                    webhook_endpoint_id=wh.id,
                    organization_id=wh.organization_id,
                    event_type=outbound['event'],
                    payload_json=endpoint_payload,
                    delivery_id=delivery_id,
                    attempt_number=1,
                    delivery_status=_DELIVERY_STATUS_PENDING,
                    next_retry_at=None,
                )
                session.add(log)
                pending_logs[wh.id] = log
                probes.append(
                    (
                        wh,
                        wire_body(endpoint_payload),
                        endpoint_payload,
                        delivery_id,
                    )
                )
            await _flush(session)

        # The probes leave the process and touch no session while they run,
        # so the fan-out races only the network — never the database. Every
        # session write (the delivery row, the breaker tally, the cut-off
        # journal and notification) happens serially after the gather: two
        # coroutines writing one AsyncSession mid-flight reset each other's
        # attribute history, and the loser's failure and its pending row
        # never reach the database — the cut-off endpoint stays active and
        # the stale-pending requeue sends the event a second time.
        import asyncio

        outcomes = await asyncio.gather(
            *(
                _attempt_delivery(wh, payload_bytes, op, delivery_id=did)
                for wh, payload_bytes, op, did in probes
            ),
            return_exceptions=True,
        )

        async with session.begin():
            threshold = await _breaker_threshold_async(session, organization_id)
            for wh, outcome in zip(matching, outcomes, strict=True):
                if isinstance(outcome, BaseException):
                    logger.error(
                        'Unhandled exception delivering to webhook %s: %s',
                        wh.id,
                        outcome,
                    )
                    continue
                _apply_delivery_outcome(pending_logs[wh.id], wh, outcome)
                await _update_stats_after_delivery(
                    session, wh, outcome[0], outcome[1], threshold
                )


def _apply_delivery_outcome(
    log: WebhookDeliveryLog,
    webhook: WebhookEndpoint,
    outcome: tuple[bool, int | None, str | None, str | None],
) -> None:
    """Fold one probe's result into its delivery row — memory only, no I/O.

    The dispatch calls this serially, one endpoint at a time after the
    probe gather, so the row's fields can never interleave with a peer's
    write on the shared session. The breaker tally itself follows through
    ``_update_stats_after_delivery`` in the same serial pass.
    """
    is_success, status_code, response_body, error_message = outcome

    log.delivery_status = (
        _DELIVERY_STATUS_SUCCESS
        if is_success
        else (
            _DELIVERY_STATUS_PENDING_RETRY
            if webhook.max_retries > 0
            else _DELIVERY_STATUS_FAILED
        )
    )
    log.next_retry_at = (
        _calc_next_retry(1, webhook)
        if not is_success and webhook.max_retries > 0
        else None
    )
    log.status_code = status_code
    log.response_body = response_body
    log.error_message = error_message
    # The attempt's own end time: created_at ages away from the outcome by
    # the whole backoff, and the history reads this when it has it.
    log.last_attempt_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Test delivery (for the /test endpoint)
# ---------------------------------------------------------------------------


def _test_ping_failure(
    status_code: int | None, error_message: str | None
) -> str | None:
    """What the caller of a test ping is told when the receiver did not take it.

    A refusal arrives with the receiver's whole response as its error, and a
    405 from a web server is a page of HTML. That body is evidence for the
    delivery log, where it was stored for deliberate reading; the answer to
    "which side refused, and how" is the status. A failure with no status
    (a timeout, an unreachable host) already carries a short reason of its own.
    """
    if error_message is None or status_code is None:
        return error_message
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = ''
    return f'The receiver answered {status_code} {phrase}'.strip()


async def deliver_test_ping(
    db: AsyncSession,
    webhook: WebhookEndpoint,
    user_organization_id: str,
) -> tuple[bool, int | None, str | None, UUID]:
    """Send a test ping payload to *webhook*.

    Returns (success, status_code, error_message, delivery_id).
    """
    delivery_id = uuid4()
    # The ping travels in the same envelope as a real event, so a receiver
    # validated against it accepts the first delivery that follows.
    ping = TenantEventPayload.model_validate(
        {
            'organization_id': str(user_organization_id),
            'webhook_id': str(webhook.id),
            'message': 'This is a test ping from Inventari Webhooks module.',
        }
    )
    outbound = _serialize_payload(
        {
            **build_outbound_payload('webhook.test', ping),
            'delivery_id': str(delivery_id),
        }
    )
    payload_bytes = wire_body(outbound)

    is_success, status_code, response_body, error_message = await _attempt_delivery(
        webhook, payload_bytes, outbound, delivery_id=str(delivery_id)
    )

    # Log it
    log = WebhookDeliveryLog(
        webhook_endpoint_id=webhook.id,
        organization_id=webhook.organization_id,
        event_type='webhook.test',
        payload_json=outbound,
        delivery_id=str(delivery_id),
        status_code=status_code,
        response_body=response_body,
        error_message=error_message,
        attempt_number=1,
        delivery_status=_DELIVERY_STATUS_SUCCESS
        if is_success
        else _DELIVERY_STATUS_FAILED,
        next_retry_at=None,
        last_attempt_at=datetime.now(UTC),
    )
    db.add(log)
    # One probe, one session — the read can sit beside the tally, but it
    # goes through the same helper so every path states one policy.
    threshold = await _breaker_threshold_async(db, webhook.organization_id)
    await _update_stats_after_delivery(db, webhook, is_success, status_code, threshold)
    # The caller owns the commit: flush here and let the request dependency
    # close the unit of work (this used to commit mid-stack).
    await _flush(db)

    return (
        is_success,
        status_code,
        _test_ping_failure(status_code, error_message),
        delivery_id,
    )
