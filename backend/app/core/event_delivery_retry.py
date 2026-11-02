"""Retry worker for event handlers that failed on a stream delivery.

The bus writes an ``event_deliveries`` row when a handler raises (or outlasts
its bound) instead of acknowledging the event and forgetting it. This worker
runs each due row's handler again — that handler alone, never the event's
other subscribers — and either marks it ``succeeded``, schedules the next
attempt with doubling backoff, or, after ``MAX_HANDLER_ATTEMPTS``, parks it
as ``dead`` (the dead-letter queue) and warns the organization's admins.

Registered as a frequent local scheduled task next to the outbox relay; the
rows are claimed with ``FOR UPDATE SKIP LOCKED``, so two nodes never run the
same retry at once.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core._event_bus import (
    MAX_HANDLER_ATTEMPTS,
    EventBus,
    event_bus,
    retry_delay,
)
from app.core._event_types import EventPayload, TenantEventPayload
from app.core.contracts import NotificationDedupKey
from app.core.logging import get_logger
from app.i18n.service import SUPPORTED_LANGUAGES, get_error_message
from app.models.event_delivery import EventDelivery

logger = get_logger(__name__)

RETRY_BATCH_LIMIT = 50

#: One unread alert per handler per day: a handler that is broken for good
#: fails on every event, and each of them would otherwise ring the bell.
_ALERT_DEDUP_WINDOW = timedelta(days=1)

_DEAD_TITLE: dict[str, str] = {
    str(lang): get_error_message('event_delivery_dead_title', lang)
    for lang in SUPPORTED_LANGUAGES
}
_DEAD_CONTENT: dict[str, str] = {
    str(lang): get_error_message('event_delivery_dead_content', lang)
    for lang in SUPPORTED_LANGUAGES
}


def _payload_of(row: EventDelivery) -> EventPayload:
    """Rebuild the payload the way the stream consumer does."""
    if 'organization_id' in row.payload:
        return TenantEventPayload(**row.payload)
    return EventPayload(**row.payload)


async def _alert_admins(db: AsyncSession, row: EventDelivery) -> list[Any]:
    """Warn the organization's admins that a handler was given up on.

    Returns the notifications written, for the caller to publish once its
    commit has made them real.
    """
    from app.core.public_api import core_api

    if row.organization_id is None:
        # A non-tenant event has no admins to tell; the row and the log
        # are the record.
        return []
    key = NotificationDedupKey(
        meta_type='event_delivery_dead', ref_key='handler', ref_id=row.handler
    )
    since = datetime.now(UTC) - _ALERT_DEDUP_WINDOW
    if await core_api.notifications.exists_unread_by_meta_async(
        db, row.organization_id, key, since
    ):
        return []
    return await core_api.notifications.notify_org_admins_async(
        db,
        row.organization_id,
        title=_DEAD_TITLE,
        content=core_api.notifications.localize(
            _DEAD_CONTENT,
            handler=row.handler,
            event=row.event,
            attempts=row.attempts,
            # The column holds 1000 characters, and a traceback's message
            # can be longer; the row keeps it whole.
            error=(row.last_error or '—')[:300],
        ),
        notification_type='error',
        meta_data={
            'type': 'event_delivery_dead',
            'handler': row.handler,
            'event': row.event,
            'event_id': row.event_id,
        },
    )


async def _give_up(db: AsyncSession, row: EventDelivery) -> list[Any]:
    row.status = 'dead'
    row.next_attempt_at = None
    logger.error(
        '[EventDelivery] Handler %s for %s (event %s) failed %d times — parked '
        'as dead: %s',
        row.handler,
        row.event,
        row.event_id,
        row.attempts,
        row.last_error,
    )
    return await _alert_admins(db, row)


async def _retry_one(db: AsyncSession, bus: EventBus, row: EventDelivery) -> list[Any]:
    """Run the row's handler once more; return any alert to publish."""
    callback = bus.find_handler(
        row.event,
        row.handler,
        str(row.organization_id) if row.organization_id else None,
    )
    if callback is None:
        # Unsubscribed since (a module switched off or uninstalled): nothing
        # will ever run it again, so waiting out the attempts only delays
        # the alert.
        row.last_error = f'No handler named {row.handler} is subscribed any more'
        return await _give_up(db, row)

    error = await bus.run_handler(row.event, callback, _payload_of(row))
    row.attempts += 1
    if error is None:
        row.status = 'succeeded'
        row.next_attempt_at = None
        logger.info(
            '[EventDelivery] Handler %s for %s succeeded on attempt %d',
            row.handler,
            row.event,
            row.attempts,
        )
        return []
    row.last_error = error
    if row.attempts >= MAX_HANDLER_ATTEMPTS:
        return await _give_up(db, row)
    row.next_attempt_at = datetime.now(UTC) + retry_delay(row.attempts)
    return []


async def retry_failed_deliveries(
    sessions: Any, bus: EventBus = event_bus, batch_limit: int = RETRY_BATCH_LIMIT
) -> int:
    """Run every due failed handler once; return how many were run.

    Each row gets a session and a transaction of its own — claimed with
    ``FOR UPDATE SKIP LOCKED``, committed as soon as its handler has run —
    so a crash mid-batch keeps the attempts already counted, and a slow
    handler holds one row's lock, not the batch's.
    """
    from app.core.public_api import core_api

    now = datetime.now(UTC)
    async with sessions() as db:
        ids: list[UUID] = list(
            (
                await db.execute(
                    select(EventDelivery.id)
                    .where(
                        EventDelivery.status == 'retrying',
                        EventDelivery.next_attempt_at <= now,
                    )
                    .order_by(EventDelivery.next_attempt_at)
                    .limit(batch_limit)
                )
            )
            .scalars()
            .all()
        )
    ran = 0
    for delivery_id in ids:
        async with sessions() as db:
            async with db.begin():
                row = (
                    await db.execute(
                        select(EventDelivery)
                        .where(
                            EventDelivery.id == delivery_id,
                            EventDelivery.status == 'retrying',
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).scalar_one_or_none()
                if row is None:
                    continue  # another node has it, or it settled meanwhile
                alerts = await _retry_one(db, bus, row)
            await core_api.notifications.publish_async(db, alerts)
        ran += 1
    return ran


async def retry_failed_deliveries_once() -> None:
    """Scheduled-task entry point: run one batch on the application's sessions."""
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        return
    try:
        ran = await retry_failed_deliveries(db_facade.AsyncSessionLocal)
        if ran:
            logger.info('[EventDelivery] Retried %d failed handler(s)', ran)
    except (SQLAlchemyError, OSError) as exc:
        # Handler failures are caught per handler; what reaches here is the
        # log itself being unreachable, and the next tick tries again.
        logger.error('[EventDelivery] Retry batch failed: %s', exc)
