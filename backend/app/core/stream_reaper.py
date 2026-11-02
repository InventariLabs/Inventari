"""Periodic reaper for Redis stream pending entries.

Registered as a local scheduled task in the app lifespan; the scheduler's
tick lock guarantees only one cluster node reaps per tick. Reclaims stale pending
entries (consumer crashed before ACK) on both the event stream and the
persistent task stream via XAUTOCLAIM.
"""

from app.core._event_bus import event_bus
from app.core.logging import get_logger
from app.core.scheduler import task_scheduler

logger = get_logger(__name__)


async def reap_streams_once() -> None:
    """Reclaim stale pending entries on event + task streams."""
    events = await event_bus.reclaim_pending_events()
    tasks = await task_scheduler.reclaim_pending_tasks()
    if events or tasks:
        logger.info(
            '[StreamReaper] Reclaimed %d event(s) and %d task(s)', events, tasks
        )
