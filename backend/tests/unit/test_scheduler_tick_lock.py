"""Unit tests for the scheduler cluster-safe tick lock.

With N app workers, each periodic tick must execute (or enqueue) on exactly
one node. The lock is a Redis ``SET NX EX`` keyed per task; without Redis the
tick always runs (dev/single-node fallback).
"""

import time
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.scheduler import ScheduledTask, TaskScheduler


class FakeRedis:
    """Minimal async Redis stub honoring SET NX EX semantics."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    async def set(
        self, key: str, value: str, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        existing = self._store.get(key)
        if existing is not None and existing[1] is not None:
            if existing[1] <= time.monotonic():
                existing = None
        if nx and existing is not None:
            return None
        expiry = time.monotonic() + ex if ex is not None else None
        self._store[key] = (value, expiry)
        return True

    def expire_key(self, key: str) -> None:
        """Force-expire a key (test helper)."""
        if key in self._store:
            self._store[key] = (self._store[key][0], 0.0)


def _task(name: str = 't', seconds: float = 60) -> ScheduledTask:
    return ScheduledTask(
        name=name,
        interval=timedelta(seconds=seconds),
        handler=AsyncMock(),
        module_name='mod',
    )


async def _run_one_tick(node: TaskScheduler, task: ScheduledTask) -> None:
    """Drive exactly one periodic tick: jitter sleep is skipped, the first
    interval sleep stops the loop."""
    node._running = True
    calls = 0

    async def stop_after_interval(delay: float) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:  # first call = initial jitter, second = post-tick
            node._running = False

    with patch(
        'app.core.scheduler.asyncio.sleep',
        new_callable=AsyncMock,
        side_effect=stop_after_interval,
    ):
        await node._run_periodic(task)


@pytest.mark.unit
class TestAcquireTickLock:
    async def test_first_node_acquires_second_node_skips(self):
        redis = FakeRedis()
        node_a, node_b = TaskScheduler(), TaskScheduler()
        node_a._redis = redis
        node_b._redis = redis

        task = _task()
        assert await node_a._acquire_tick_lock(task) is True
        assert await node_b._acquire_tick_lock(task) is False

    async def test_lock_expires_and_next_tick_runs(self):
        redis = FakeRedis()
        node_a = TaskScheduler()
        node_a._redis = redis
        task = _task()

        assert await node_a._acquire_tick_lock(task) is True
        redis.expire_key(f'scheduler:tick:{task.key}')
        assert await node_a._acquire_tick_lock(task) is True

    async def test_lock_ttl_is_80_percent_of_interval_min_1s(self):
        redis = FakeRedis()
        node = TaskScheduler()
        node._redis = redis

        await node._acquire_tick_lock(_task(name='short', seconds=1))
        await node._acquire_tick_lock(_task(name='long', seconds=100))

        now = time.monotonic()
        short_ttl = redis._store['scheduler:tick:mod.short'][1] - now
        long_ttl = redis._store['scheduler:tick:mod.long'][1] - now
        assert 0 < short_ttl <= 1
        assert 79 < long_ttl <= 80

    async def test_no_redis_always_runs(self):
        node = TaskScheduler()
        assert await node._acquire_tick_lock(_task()) is True

    async def test_redis_error_fails_open(self):
        class BrokenRedis:
            async def set(self, *args, **kwargs):
                from redis.exceptions import RedisError

                raise RedisError('connection lost')

        node = TaskScheduler()
        node._redis = BrokenRedis()
        assert await node._acquire_tick_lock(_task()) is True


@pytest.mark.unit
class TestRunPeriodicWithTickLock:
    async def test_node_holding_lock_executes_handler(self):
        redis = FakeRedis()
        handler = AsyncMock()
        task = ScheduledTask(
            name='shared',
            interval=timedelta(seconds=60),
            handler=handler,
            module_name='mod',
        )
        node = TaskScheduler()
        node._redis = redis

        await _run_one_tick(node, task)
        handler.assert_awaited_once()

    async def test_node_without_lock_skips_execution(self):
        """Lock pre-held by another node id → handler never runs."""
        redis = FakeRedis()
        task = ScheduledTask(
            name='shared',
            interval=timedelta(seconds=60),
            handler=AsyncMock(),
            module_name='mod',
        )

        holder = TaskScheduler()
        holder._redis = redis
        assert await holder._acquire_tick_lock(task) is True

        handler = AsyncMock()
        task.handler = handler
        contender = TaskScheduler()
        contender._redis = redis

        await _run_one_tick(contender, task)
        handler.assert_not_called()

    async def test_persistent_task_not_enqueued_without_lock(self):
        redis = FakeRedis()
        task = ScheduledTask(
            name='persist',
            interval=timedelta(seconds=60),
            handler=AsyncMock(),
            module_name='mod',
            is_persistent=True,
        )

        holder = TaskScheduler()
        holder._redis = redis
        assert await holder._acquire_tick_lock(task) is True

        contender = TaskScheduler()
        contender._redis = redis
        contender.enqueue = AsyncMock()

        await _run_one_tick(contender, task)
        contender.enqueue.assert_not_called()
