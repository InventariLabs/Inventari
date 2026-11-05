"""
Lightweight async task scheduler for module periodic tasks.

Design decisions:
- Uses the asyncio event loop for local execution.
- Supports Redis-backed persistent task queuing for critical jobs.
- Tasks run in the same process as the FastAPI application by default.
- Scheduler is started after all module ``on_startup`` hooks have run.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings
from app.core._redis_streams import prune_consumers, xautoclaim_messages
from app.core.logging import get_logger
from app.core.module_identity import module_scope
from app.core.schema_rebuild import schema_held_steady

logger = get_logger(__name__)


@dataclass
class ScheduledTask:
    """Metadata for a single registered periodic task."""

    name: str
    interval: timedelta
    handler: Callable[..., Any]
    module_name: str
    is_persistent: bool = False
    _task: asyncio.Task[Any] | None = field(default=None, repr=False)

    @property
    def key(self) -> str:
        return f'{self.module_name}.{self.name}'

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()


class TaskScheduler:
    """In-process and Redis-backed periodic task scheduler.

    Supports two modes:
    1. Local (In-memory): Fast, no overhead, lost on restart.
    2. Persistent (Redis Streams): Guaranteed execution, survives restart.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._running: bool = False
        self._redis: Redis | None = None
        self._stream_name = settings.REDIS_TASKS_STREAM_NAME
        self._group_name = 'inventari_task_workers'
        self._node_id = str(uuid.uuid4())

    async def connect(self, redis_url: str) -> None:
        """Optionally connect to Redis for persistent tasks."""
        try:
            import redis.asyncio as redis

            self._redis = redis.from_url(redis_url, decode_responses=True)

            # Ensure consumer group exists
            try:
                assert self._redis is not None
                await self._redis.xgroup_create(
                    self._stream_name, self._group_name, id='0', mkstream=True
                )
            except redis.ResponseError as e:
                if 'BUSYGROUP' not in str(e):
                    raise

            logger.info('[Scheduler] Connected to Redis for persistent tasks.')
        except (RedisError, OSError) as e:
            logger.warning('[Scheduler] Redis task persistence disabled: %s', e)

    def register(
        self,
        name: str,
        interval: timedelta,
        handler: Callable[[], Any],
        module_name: str,
        is_persistent: bool = False,
    ) -> None:
        """Register a periodic task."""
        task = ScheduledTask(
            name=name,
            interval=interval,
            handler=handler,
            module_name=module_name,
            is_persistent=is_persistent,
        )
        self._tasks[task.key] = task
        logger.info(
            '[Scheduler] Registered %s task: %s (every %s)',
            'persistent' if is_persistent else 'local',
            task.key,
            interval,
        )

        if self._running:
            task._task = asyncio.create_task(self._run_periodic(task))

    def unregister(self, name: str, module_name: str) -> bool:
        """Unregister a periodic task. Returns True when the task existed.

        A running task is cancelled. Unknown keys are a no-op (safe to call
        during module disable even if registration never happened).
        """
        key = f'{module_name}.{name}'
        task = self._tasks.pop(key, None)
        if task is None:
            return False
        if task.is_running and task._task is not None:
            task._task.cancel()
        logger.info('[Scheduler] Unregistered task: %s', key)
        return True

    def start_all(self) -> None:
        """Start all registered tasks and the persistent worker loop."""
        if self._running:
            return
        self._running = True

        for task in self._tasks.values():
            task._task = asyncio.create_task(self._run_periodic(task))
            logger.info('[Scheduler] Started task: %s', task.key)

        if self._redis:
            asyncio.create_task(self._run_persistent_worker())

    def stop_all(self) -> None:
        """Cancel all running tasks (fire-and-forget; use stop_all_async for clean await)."""
        self._running = False
        for task in self._tasks.values():
            if task.is_running and task._task is not None:
                task._task.cancel()
        logger.info('[Scheduler] Stopped all tasks (%d total)', len(self._tasks))

    async def stop_all_async(self) -> None:
        """Cancel all running tasks and await their completion for clean shutdown."""
        self.stop_all()
        pending = [
            task._task
            for task in self._tasks.values()
            if task._task is not None and not task._task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def enqueue(
        self, task_key: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Manually enqueue a persistent task for execution."""
        if not self._redis:
            logger.error(
                '[Scheduler] Cannot enqueue %s: Redis not connected.', task_key
            )
            return

        message: dict[str, Any] = {
            'task_key': task_key,
            'payload': json.dumps(payload or {}),
        }
        await self._redis.xadd(
            self._stream_name,
            message,  # type: ignore[arg-type]
            maxlen=settings.TASK_STREAM_MAXLEN,
            approximate=True,
        )
        logger.debug('[Scheduler] Enqueued persistent task: %s', task_key)

    async def _acquire_tick_lock(self, task: ScheduledTask) -> bool:
        """Cluster-wide mutual exclusion for one task tick.

        ``SET NX EX`` ensures that with N app workers only one node executes
        (or enqueues) a given tick. The lock expires at ~80% of the interval
        (min 1s) so a dead node costs at most one missed tick. Without Redis
        (dev/single-node) or on Redis errors the tick always runs — the
        pre-lock behavior is the safe fallback.
        """
        if not self._redis:
            return True
        ttl = max(1, int(task.interval.total_seconds() * 0.8))
        try:
            acquired = await self._redis.set(
                f'scheduler:tick:{task.key}', self._node_id, nx=True, ex=ttl
            )
        except (RedisError, OSError) as e:
            logger.warning(
                '[Scheduler] Tick lock unavailable for %s (%s) — running locally.',
                task.key,
                e,
            )
            return True
        return bool(acquired)

    async def _run_periodic(self, task: ScheduledTask) -> None:
        """Main loop for a single task."""
        # Initial jitter
        await asyncio.sleep(min(5.0, task.interval.total_seconds() * 0.1))

        while self._running:
            try:
                if await self._acquire_tick_lock(task):
                    if task.is_persistent and self._redis:
                        # For persistent tasks, we just enqueue them to the stream
                        # The worker loop will pick them up and execute.
                        await self.enqueue(task.key)
                    else:
                        # Local execution
                        await self._execute_task(task)
                else:
                    logger.debug(
                        '[Scheduler] Tick skipped (lock held by another node): %s',
                        task.key,
                    )
            except asyncio.CancelledError:
                break
            except Exception:  # persistent worker loop must never crash on task failure
                logger.exception('[Scheduler] Task loop failed: %s', task.key)

            await asyncio.sleep(task.interval.total_seconds())

    async def _execute_task(
        self, task: ScheduledTask, payload: dict[str, Any] | None = None
    ) -> None:
        """Safely execute the task handler.

        The handler runs under its module's identity: a periodic job is
        the module's own code with no request around it, and without this
        a job reading its settings or emitting an event had no identity —
        which failed the moment those seams started refusing anonymous
        foreign names, and attributed nothing before that.

        The demo rebuilds its schema under a running backend, so there a job
        holds the schema still for as long as it runs and is skipped while a
        rebuild is under way; the next tick finds the schema whole again.
        Every way a job starts (a tick, the stream worker, a reclaimed
        message) comes through here.
        """
        steady = schema_held_steady() if settings.INVENTARI_DEMO else nullcontext(True)
        try:
            async with steady as may_run:
                if not may_run:
                    logger.debug(
                        '[Scheduler] Job skipped (the database is being rebuilt): %s',
                        task.key,
                    )
                    return
                with module_scope(task.module_name):
                    result = (
                        task.handler() if payload is None else task.handler(payload)
                    )
                    if asyncio.iscoroutine(result):
                        await result
        except Exception:  # task handler exceptions are logged and must not propagate
            logger.exception('[Scheduler] Execution failed for task: %s', task.key)

    async def reclaim_pending_tasks(
        self, min_idle_ms: int | None = None, count: int = 100
    ) -> int:
        """XAUTOCLAIM stale pending task messages to this node and execute them.

        A worker that read a task message but crashed before ACK leaves it
        pending forever without this reaper. Returns the number of
        reclaimed + executed tasks.
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
            label='Scheduler',
        )

        reclaimed = 0
        for msg_id, data in messages:
            if data:
                task_key = data.get('task_key')
                payload = json.loads(data.get('payload', '{}'))
                task = self._tasks.get(task_key) if task_key else None
                if task:
                    await self._execute_task(task, payload)
                else:
                    logger.warning(
                        '[Scheduler] Reclaimed unknown task key: %s', task_key
                    )
                reclaimed += 1
            await self._redis.xack(self._stream_name, self._group_name, msg_id)
        if reclaimed:
            logger.info('[Scheduler] Reclaimed %d pending task(s)', reclaimed)
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
            label='Scheduler',
        )

    async def _run_persistent_worker(self) -> None:
        """Background loop that pulls persistent tasks from Redis Stream."""
        logger.info('[Scheduler] Persistent worker loop started.')

        while self._running:
            try:
                # Read from group
                assert self._redis is not None
                streams = await self._redis.xreadgroup(
                    self._group_name,
                    self._node_id,
                    {self._stream_name: '>'},
                    count=1,
                    block=2000,
                )

                if not streams:
                    continue

                for _, messages in streams:  # type: ignore[str-unpack]
                    for msg_id, data in messages:  # type: ignore[str-unpack,union-attr]
                        task_key = data.get('task_key')  # type: ignore[union-attr]
                        payload = json.loads(data.get('payload', '{}'))  # type: ignore[union-attr]

                        task = self._tasks.get(task_key)
                        if task:
                            await self._execute_task(task, payload)
                        else:
                            logger.warning(
                                f'[Scheduler] Received unknown task key from stream: {task_key}'
                            )

                        # ACK task
                        assert self._redis is not None
                        await self._redis.xack(
                            self._stream_name, self._group_name, msg_id
                        )

            except asyncio.CancelledError:
                break
            except (RedisError, OSError, ValueError) as e:
                logger.error('[Scheduler] Persistent worker error: %s', e)
                await asyncio.sleep(1)


# Global singleton
task_scheduler = TaskScheduler()
