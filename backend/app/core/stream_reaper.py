"""Periodic reaper for Redis stream pending entries.

Registered as a local scheduled task in the app lifespan; the scheduler's
tick lock guarantees only one cluster node reaps per tick. Reclaims stale pending
entries (consumer crashed before ACK) on both the event stream and the
persistent task stream via XAUTOCLAIM, then forgets the consumers of
processes that are gone (a graceful shutdown removes its own; a crash cannot).
"""

from app.core._event_bus import event_bus
from app.core.logging import get_logger
from app.core.scheduler import task_scheduler

logger = get_logger(__name__)

#: A consumer with nothing pending that has not touched the stream for this
#: long belongs to a process that is gone: a live one polls every second, and
#: Redis counts the poll as activity.
DEAD_CONSUMER_IDLE_MS = 60 * 60 * 1000


async def reap_streams_once() -> None:
    """Reclaim stale pending entries on event + task streams."""
    events = await event_bus.reclaim_pending_events()
    tasks = await task_scheduler.reclaim_pending_tasks()
    if events or tasks:
        logger.info(
            '[StreamReaper] Reclaimed %d event(s) and %d task(s)', events, tasks
        )
    # After the reclaim: whatever a dead consumer still held is ours now, so
    # only the empty-handed ones are left to remove.
    await event_bus.prune_dead_consumers(DEAD_CONSUMER_IDLE_MS)
    await task_scheduler.prune_dead_consumers(DEAD_CONSUMER_IDLE_MS)
