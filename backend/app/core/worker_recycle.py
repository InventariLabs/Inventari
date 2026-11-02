"""Give a web worker's memory back by replacing the worker.

Python does not return the memory of a large answer to the system: a worker
that built a 700 KB tree, a zone's occupancy or a statistics page keeps the
heap it grew to, and four workers holding 600–900 MB each fill any limit the
host can give — the container then kills one of them, and every request it was
answering dies with it. Replacing a worker is the one reliable way to hand the
memory back, so a worker replaces itself:

- **between requests**, once it has grown more than ``max_growth_mb`` over its
  own start-up size, and
- **when it sits idle** for ``idle_seconds`` more than a quarter over its
  start-up size.

The size it is measured against is its own, read once the worker is up and
quiet, so the rule follows the application as it grows instead of a number
that has to be re-guessed per release. The worker leaves through the graceful stop gunicorn's arbiter itself uses
(SIGTERM): it finishes what it is answering, and the arbiter starts a fresh one.

The application's lifespan starts the watch (:func:`start_watch`), and
:class:`CountRequests` tells it when a request is in flight and
:func:`hold_until_done` when a background job is. The variables are
``BACKEND_WORKER_MAX_GROWTH_MB`` (default 200) and
``BACKEND_WORKER_IDLE_RECYCLE_SECONDS`` (default 120; 0 turns the idle rule
off).
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

#: How much over its start-up size an idle worker may sit before it is replaced.
IDLE_GROWTH_FACTOR = 1.25

#: An idle worker is not replaced for a growth this small, whatever the ratio:
#: the replacement itself costs more than the memory it would give back.
IDLE_GROWTH_FLOOR_MB = 32.0

#: Seconds between looks at the worker's size.
CHECK_INTERVAL_SECONDS = 15.0


def read_rss_mb() -> float:
    """This process's resident memory in MB, from ``/proc`` (0 where there is none)."""
    try:
        with open('/proc/self/statm') as statm:
            pages = int(statm.read().split()[1])
    except (OSError, ValueError, IndexError):
        return 0.0
    return pages * os.sysconf('SC_PAGE_SIZE') / (1024 * 1024)


class WorkerRecycler:
    """When a worker should be replaced, from its size and its traffic."""

    def __init__(
        self,
        *,
        max_growth_mb: float,
        idle_seconds: float,
        rss_mb: Callable[[], float] = read_rss_mb,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_growth_mb = max_growth_mb
        self.idle_seconds = idle_seconds
        self._rss_mb = rss_mb
        self._clock = clock
        self._lock = threading.Lock()
        self._in_flight = 0
        self._last_activity = clock()
        self.baseline_mb: float | None = None

    def request_started(self) -> None:
        with self._lock:
            self._in_flight += 1
            self._last_activity = self._clock()

    def request_finished(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._last_activity = self._clock()

    def reason_to_replace(self) -> str | None:
        """Why the worker should leave now, or ``None`` to stay.

        Nothing is decided while a request is in flight: the worker is not
        idle, and a request that just finished is the moment to look.
        """
        with self._lock:
            if self._in_flight:
                return None
            idle_for = self._clock() - self._last_activity
        rss = self._rss_mb()
        if rss <= 0:
            return None
        if self.baseline_mb is None:
            # The first quiet look: the application is loaded and nothing is
            # being answered, which is the size the rest is measured against.
            self.baseline_mb = rss
            return None
        grown = rss - self.baseline_mb
        if self.max_growth_mb > 0 and grown > self.max_growth_mb:
            return f'{rss:.0f} MB, {grown:.0f} MB over its start-up size'
        if (
            self.idle_seconds > 0
            and idle_for >= self.idle_seconds
            and grown > IDLE_GROWTH_FLOOR_MB
            and rss > self.baseline_mb * IDLE_GROWTH_FACTOR
        ):
            return f'{rss:.0f} MB after {idle_for:.0f} s idle, start-up {self.baseline_mb:.0f} MB'
        return None


#: The recycler of the worker this process is, once :func:`start_watch` has run.
active: WorkerRecycler | None = None


class CountRequests:
    """ASGI middleware: tells the recycler when an HTTP request starts and ends."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        recycler = active
        if scope['type'] != 'http' or recycler is None:
            await self.app(scope, receive, send)
            return
        recycler.request_started()
        try:
            await self.app(scope, receive, send)
        finally:
            recycler.request_finished()


def hold_until_done(task: asyncio.Task[Any]) -> None:
    """Count a background task as work in flight until it finishes.

    A job the worker runs for a request outlives that request, and the worker
    leaving under it would cancel it half way.
    """
    recycler = active
    if recycler is None:
        return
    recycler.request_started()
    task.add_done_callback(lambda _task: recycler.request_finished())


def start_watch() -> asyncio.Task[None] | None:
    """Watch this worker's size from the event loop, or do nothing.

    Only a process told to (``BACKEND_WORKER_MAX_GROWTH_MB`` set in its
    environment, as the production compose file does) watches itself: a
    development server or a test run is not a worker an arbiter replaces,
    and a process that asked to be stopped there would simply stop.

    The worker leaves by SIGTERM to itself, the signal gunicorn's arbiter
    sends for a graceful stop: the worker finishes what it is answering,
    and the arbiter starts a fresh one.
    """
    global active
    growth = os.environ.get('BACKEND_WORKER_MAX_GROWTH_MB')
    if not growth:
        return None
    recycler = WorkerRecycler(
        max_growth_mb=float(growth),
        idle_seconds=float(
            os.environ.get('BACKEND_WORKER_IDLE_RECYCLE_SECONDS', '120')
        ),
    )
    active = recycler

    async def _watch() -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            reason = recycler.reason_to_replace()
            if reason:
                logger.info('Replacing worker (pid:%s): %s', os.getpid(), reason)
                os.kill(os.getpid(), signal.SIGTERM)
                return

    return asyncio.create_task(_watch())
