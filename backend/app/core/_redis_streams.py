"""Shared Redis Streams plumbing.

Both the EventBus and the TaskScheduler reclaim stale pending entries via
XAUTOCLAIM and tidy their consumer group — same call shapes, same redis-py
response unpacking. Kept here so the two only implement their own message
handling.
"""

from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.core.logging import get_logger

logger = get_logger(__name__)


async def xautoclaim_messages(
    redis_client: redis.Redis,
    stream: str,
    group: str,
    consumer: str,
    min_idle_ms: int,
    count: int = 100,
    label: str = 'Stream',
) -> list[tuple[str, dict[str, Any]]]:
    """XAUTOCLAIM up to ``count`` stale pending entries to ``consumer``.

    Returns ``[(message_id, data), ...]``; entries with empty ``data`` were
    trimmed from the stream and only need an ACK to drop the pending
    reference. On Redis errors logs and returns an empty list (the next
    reaper tick retries).
    """
    try:
        result = await redis_client.xautoclaim(
            stream,
            group,
            consumer,
            min_idle_time=min_idle_ms,
            count=count,
        )
    except (RedisError, OSError) as e:
        logger.error('[%s] XAUTOCLAIM failed: %s', label, e)
        return []
    # redis-py returns (next_start_id, [(msg_id, data), ...], deleted_ids)
    messages = result[1] if len(result) >= 2 else []
    return [(msg_id, data) for msg_id, data in messages]


async def prune_consumers(
    redis_client: redis.Redis,
    stream: str,
    group: str,
    *,
    min_idle_ms: int,
    keep: str | None = None,
    only: str | None = None,
    label: str = 'Stream',
) -> int:
    """XGROUP DELCONSUMER the consumers of ``group`` that hold nothing.

    A consumer name is a process's node id, so every restart or crash leaves
    one behind; Redis never forgets it. A consumer is removed only when it
    has **no pending entries** (DELCONSUMER would silently drop them, and
    they are exactly what reclaim exists to recover) and has been idle for
    ``min_idle_ms``. ``keep`` is never removed; with ``only`` set, no other
    consumer is looked at. Returns how many were removed; Redis errors are
    logged and end the pass (the next one retries).
    """
    try:
        consumers = await redis_client.xinfo_consumers(stream, group)
        removed = 0
        for consumer in consumers:
            name = consumer['name']
            if name == keep or (only is not None and name != only):
                continue
            if consumer['pending'] or consumer['idle'] < min_idle_ms:
                continue
            await redis_client.xgroup_delconsumer(stream, group, name)
            removed += 1
    except (RedisError, OSError) as e:
        logger.error('[%s] Consumer cleanup failed: %s', label, e)
        return 0
    if removed:
        logger.info('[%s] Removed %d idle consumer(s) from the group', label, removed)
    return removed
