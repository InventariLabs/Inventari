import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_claim import due_or_zombie_clause
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint

from ._module_gate import webhooks_enabled_async
from ._webhook_constants import (
    _ABANDON_CIRCUIT_BREAKER,
    _ABANDON_MODULE_DISABLED,
    _ABANDON_WEBHOOK_DELETED,
    _ABANDON_WEBHOOK_DISABLED,
    _DELIVERY_STATUS_FAILED,
    _DELIVERY_STATUS_PENDING,
    _DELIVERY_STATUS_PENDING_RETRY,
    _DELIVERY_STATUS_SUCCESS,
    _RETRY_BATCH_LIMIT,
)
from ._webhook_delivery import (
    _attempt_delivery,
    _breaker_threshold_async,
    _calc_next_retry,
    _update_stats_after_delivery,
)

logger = get_logger(__name__)

_DELIVERY_STATUS_RETRYING = 'retrying'


def _abandon_delivery(log: WebhookDeliveryLog, reason: str) -> None:
    """Fold an application-side stop into the row — memory only, no I/O.

    Nobody answered: the previous attempt's status code is someone else's
    reply and must not survive as this row's answer, and the reason travels
    as a stable value the history view translates. The scheduled retry goes
    with it — a delivery we stopped must not keep promising a next attempt
    to readers of the delivery API (our own view hides the field behind the
    status; the raw API does not).
    """
    log.delivery_status = _DELIVERY_STATUS_FAILED
    log.status_code = None
    log.response_body = None
    log.error_message = None
    log.next_retry_at = None
    log.abandon_reason = reason
    log.last_attempt_at = datetime.now(UTC)


# Orphaned first attempts (status 'pending') are requeued after this
# flat grace period — they have no endpoint row lock context, so a generous
# constant beats per-endpoint math here.
_PENDING_STALE_AFTER = timedelta(minutes=5)


async def _claim_batch(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Claim a batch of due deliveries in one short transaction.

       Rows become ``retrying`` with ``claimed_at = now`` so other workers skip
    them — but the lock is released at commit, BEFORE any HTTP call.
       Zombie claims (``retrying`` with a stale ``claimed_at``) are
       reclaimed here; a claim is stale once it exceeds 2× the endpoint's own
       ``timeout_seconds`` — by then any legitimate in-flight attempt has
       finished or timed out.
    """
    stmt = (
        select(WebhookDeliveryLog)
        .outerjoin(
            WebhookEndpoint,
            WebhookDeliveryLog.webhook_endpoint_id == WebhookEndpoint.id,
        )
        .where(
            due_or_zombie_clause(
                status_col=WebhookDeliveryLog.delivery_status,
                pending_status=_DELIVERY_STATUS_PENDING_RETRY,
                inflight_status=_DELIVERY_STATUS_RETRYING,
                due_at_col=WebhookDeliveryLog.next_retry_at,
                claimed_col=WebhookDeliveryLog.claimed_at,
                now=now,
                # Stale once older than 2× the endpoint's own timeout_seconds
                # — any legitimate in-flight attempt has finished by then.
                zombie_cutoff=now
                - func.make_interval(
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    func.coalesce(WebhookEndpoint.timeout_seconds, 10) * 2,
                ),
            )
        )
        .with_for_update(skip_locked=True, of=WebhookDeliveryLog)
        .limit(_RETRY_BATCH_LIMIT)
    )
    result = await db.execute(stmt)
    claimed_ids: list[uuid.UUID] = []
    for row in result.scalars().all():
        row.delivery_status = _DELIVERY_STATUS_RETRYING
        row.claimed_at = now
        claimed_ids.append(row.id)
    await db.commit()
    return claimed_ids


async def _requeue_stale_pending(db: AsyncSession, now: datetime) -> int:
    """Requeue in-flight first attempts orphaned by a crash.

    dispatch_event commits a ``pending`` row BEFORE the HTTP attempt; a
    restart mid-flight leaves it pending forever. Rows older than the stale
    threshold are converted to ``pending_retry`` so the normal claim path
    delivers them.
    """
    stale_cutoff = now - _PENDING_STALE_AFTER
    result = await db.execute(
        update(WebhookDeliveryLog)
        .where(
            WebhookDeliveryLog.delivery_status == _DELIVERY_STATUS_PENDING,
            WebhookDeliveryLog.created_at < stale_cutoff,
        )
        .values(
            delivery_status=_DELIVERY_STATUS_PENDING_RETRY,
            next_retry_at=now,
        )
    )
    await db.commit()
    requeued = result.rowcount if isinstance(result, CursorResult) else 0
    if requeued:
        logger.info('[webhooks] Requeued %d stale pending first-attempt(s)', requeued)
    return requeued


async def retry_failed_deliveries(db: AsyncSession) -> None:
    """Claim-then-deliver retry loop.

    Phase 1 claims a batch in a short transaction; phase 2 performs the HTTP
    deliveries with NO row locks held and commits each result separately, so
    a slow endpoint can never pin a minute-long transaction on the hot
    delivery-log table.
    """
    now = datetime.now(UTC)
    await _requeue_stale_pending(db, now)
    claimed_ids = await _claim_batch(db, now)

    for log_id in claimed_ids:
        log = await db.get(WebhookDeliveryLog, log_id)
        if log is None or log.delivery_status != _DELIVERY_STATUS_RETRYING:
            continue  # reclaimed or resolved by a concurrent worker

        webhook = await db.scalar(
            select(WebhookEndpoint).where(WebhookEndpoint.id == log.webhook_endpoint_id)
        )

        # Abandonments say why we stopped, and nothing else: no status code
        # (nobody answered — the previous attempt's code is someone else's
        # reply, and the history used to print it under "response from the
        # target"), no borrowed error text. The reason travels as a stable
        # value the view translates, and it says WHICH of the stops this
        # was — "disabled or deleted" sent administrators looking for the
        # fault on the receiver's side when the breaker lived here.
        if not webhook or not webhook.is_active:
            if webhook is None:
                reason = _ABANDON_WEBHOOK_DELETED
            elif webhook.auto_disabled_at is not None:
                reason = _ABANDON_CIRCUIT_BREAKER
            else:
                reason = _ABANDON_WEBHOOK_DISABLED
            _abandon_delivery(log, reason)
            await db.commit()
            continue

        # The claim above is blind to modules — it reads two of this module's
        # own tables. So a row queued before the module was switched off would
        # otherwise keep being retried afterwards, which is how a delivery log
        # came to gain attempts 2 and 3 with the module off.
        if not await webhooks_enabled_async(db, webhook.organization_id):
            _abandon_delivery(log, _ABANDON_MODULE_DISABLED)
            await db.commit()
            continue

        # A row written before delivery ids existed meets the worker with a
        # NULL — mint one now and keep it, so this delivery still dedups by
        # one id from here on instead of gaining a new one per attempt.
        delivery_id = log.delivery_id or str(uuid.uuid4())
        log.delivery_id = delivery_id

        payload_bytes = json.dumps(log.payload_json, default=str).encode()
        is_success, status_code, response_body, error_message = await _attempt_delivery(
            webhook, payload_bytes, log.payload_json, delivery_id=delivery_id
        )

        log.attempt_number += 1
        log.status_code = status_code
        log.error_message = error_message
        log.response_body = response_body
        log.last_attempt_at = datetime.now(UTC)

        # One recorder for both outcomes. The retry is as real an HTTP probe
        # as the first delivery, so its result must age every marker the
        # first delivery ages — a success that arrived on the second attempt
        # used to reset the failure tally inline while last_triggered_at
        # stayed standing at the first attempt.
        #
        # The loop is sequential, so the threshold read can live here — a
        # batch may span organizations and the threshold belongs to the
        # endpoint's own one.
        threshold = await _breaker_threshold_async(db, webhook.organization_id)
        await _update_stats_after_delivery(
            db, webhook, is_success, status_code, threshold
        )
        if is_success:
            log.delivery_status = _DELIVERY_STATUS_SUCCESS
            log.next_retry_at = None
        else:
            if log.attempt_number > webhook.max_retries:
                log.delivery_status = _DELIVERY_STATUS_FAILED
                log.next_retry_at = None
            else:
                log.delivery_status = _DELIVERY_STATUS_PENDING_RETRY
                log.next_retry_at = _calc_next_retry(log.attempt_number, webhook)

        await db.commit()


async def cleanup_logs_per_organization_async(
    db: AsyncSession, default_retention_days: int = 30
) -> int:
    """Delete each organization's old delivery logs by *its own* retention.

    The loop lives here rather than in the module's task wiring because it is
    the policy, and the policy was wrong: the worker read `log_retention_days`
    from `orgs[0]` — whichever organization the installation listed first — and
    then deleted across every organization at once. Everyone kept their history
    for as long as that one had chosen.

    One organization failing is logged and skipped: the ones after it in the
    list are still cleaned in the same run instead of waiting for the next day.

    Returns how many rows were deleted in total.
    """
    deleted = 0
    # Ids up front: a rollback below expires the organization objects, and the
    # ones still waiting in the list must not reach back to the database.
    org_ids = [org.id for org in await core_api.organizations.list_all_async(db)]
    for org_id in org_ids:
        try:
            retention_days = default_retention_days
            persisted = await core_api.settings.get_async(
                db, org_id, 'webhooks', 'log_retention_days'
            )
            # bool is an int subclass; `True` is not a number of days.
            if isinstance(persisted, int) and not isinstance(persisted, bool):
                retention_days = persisted
            deleted += await cleanup_old_logs(
                db, retention_days=retention_days, organization_id=org_id
            )
        except Exception:  # one organization must not stop the others
            # The session is shared by the whole loop and a failed statement
            # leaves its transaction aborted: without this the next organization
            # fails too, whether the error came from the settings read, the
            # SELECT or the delete.
            await db.rollback()
            logger.exception(
                'Webhook log cleanup failed for organization %s — continuing', org_id
            )
    return deleted


async def cleanup_old_logs(
    db: AsyncSession,
    retention_days: int = 30,
    *,
    organization_id: uuid.UUID | None = None,
) -> int:
    """Delete this organization's delivery logs older than *retention_days*.

    The organization is a keyword argument rather than part of the signature's
    shape because it used to be absent entirely: the caller read
    `log_retention_days` from whichever organization the installation listed
    first and then deleted across every one of them. The module's settings
    schema promises each organization its own choice between 1 and 365 days, so
    an organization that asked for a year lost its history after thirty, and one
    that asked for a week kept it for a year — invisible on a single-tenant
    install, which is the only kind this was ever watched on.

    ``None`` still means every organization, for a caller that has already
    decided the window applies to all of them.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    stmt = select(WebhookDeliveryLog).where(WebhookDeliveryLog.created_at < cutoff)
    if organization_id is not None:
        stmt = stmt.where(WebhookDeliveryLog.organization_id == organization_id)
    result = await db.execute(stmt)
    old_logs = result.scalars().all()
    count = len(old_logs)

    for log in old_logs:
        await db.delete(log)

    if count:
        await db.commit()
        logger.info(
            'Deleted %d webhook delivery logs older than %d days', count, retention_days
        )

    return count
