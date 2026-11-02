"""Shared Redis Streams plumbing.

Both the EventBus and the TaskScheduler reclaim stale pending entries via
XAUTOCLAIM — same call shape, same redis-py response unpacking. Kept here
so the two reclaimers only implement their own message handling.
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
