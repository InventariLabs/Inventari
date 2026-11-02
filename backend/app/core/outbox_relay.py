"""Transactional outbox relay.

Publishes rows written by ``event_bus.emit_transactional`` to the Redis
event stream once their surrounding transaction has committed. Registered
as a frequent local scheduled task in the app lifespan; the scheduler's tick
lock keeps relaying single-node per tick.

Delivery is at-least-once by design: a crash between XADD and the batch
commit re-publishes the row on the next tick. Consumers must tolerate a
rare duplicate (the stream has no exactly-once semantics).
"""

import json
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core._event_bus import event_bus
from app.core.logging import get_logger
from app.models.event_outbox import EventOutbox

logger = get_logger(__name__)

RELAY_BATCH_LIMIT = 100


async def relay_outbox_batch(
    db: AsyncSession, batch_limit: int = RELAY_BATCH_LIMIT
) -> int:
    """Publish one batch of unpublished outbox rows to the event stream.

    Claims the batch with ``FOR UPDATE SKIP LOCKED``, XADDs each row, marks
    it published, and commits once. XADD is fast (local Redis), so holding
    the row locks across it is safe — unlike an outbound HTTP delivery. Returns the
    number of rows published.
    """
    redis_client = event_bus.redis
    if redis_client is None:
        return 0

    stmt = (
        select(EventOutbox)
        .where(EventOutbox.published_at.is_(None))
        .order_by(EventOutbox.created_at)
        .with_for_update(skip_locked=True)
        .limit(batch_limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    published = 0
    for row in rows:
        row.attempts += 1
        try:
            await redis_client.xadd(
                event_bus.stream_name,
                {
                    'event': row.event,
                    # The row's id, so a re-published row (see the module
                    # docstring) is the same event to the delivery log.
                    'event_id': str(row.id),
                    'sender_id': 'outbox-relay',
                    'module': row.emitter_module or '',
                    'payload': json.dumps(row.payload, default=str),
                },
                maxlen=settings.EVENT_STREAM_MAXLEN,
                approximate=True,
            )
        except (RedisError, OSError) as exc:
            logger.error('[OutboxRelay] XADD failed for row %s: %s', row.id, exc)
            continue  # stays unpublished; retried next tick
        row.published_at = datetime.now(UTC)
        published += 1

    await db.commit()
    return published


async def relay_outbox_once() -> None:
    """Scheduled-task entry point: open a session and relay one batch."""
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        return
    async with db_facade.AsyncSessionLocal() as db:
        try:
            published = await relay_outbox_batch(db)
            if published:
                logger.info('[OutboxRelay] Published %d outbox event(s)', published)
        except Exception:  # worker loop must never crash
            logger.exception('[OutboxRelay] Relay batch failed')
            await db.rollback()
