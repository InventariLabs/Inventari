"""Integration tests for Redis stream hygiene.

- XADD caps stream growth via approximate MAXLEN (event + task streams).
- Stale pending entries (consumer crashed before ACK) are reclaimed via
  XAUTOCLAIM and actually processed.
"""

import uuid
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core._event_bus import EventBus
from app.core._event_types import EventPayload, TenantEventPayload
from app.core.scheduler import TaskScheduler


@pytest.fixture(autouse=True)
def _delivery_log_on_the_test_database(
    monkeypatch: pytest.MonkeyPatch, async_engine_fixture: Any, setup_test_db: Any
) -> None:
    """The consumer reads and writes the delivery log on reclaim and on a
    failed handler; point it at this worker's database, not at whatever
    engine an earlier test left bound to another event loop."""
    monkeypatch.setattr(
        'app.database.AsyncSessionLocal',
        async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        ),
    )


async def _make_bus(stream: str, group: str) -> EventBus:
    bus = EventBus()
    bus._stream_name = stream
    bus._group_name = group
    await bus.connect(settings.REDIS_URL)
    assert bus._redis is not None, 'test requires a reachable Redis'
    return bus


async def _make_scheduler(stream: str, group: str) -> TaskScheduler:
    scheduler = TaskScheduler()
    scheduler._stream_name = stream
    scheduler._group_name = group
    await scheduler.connect(settings.REDIS_URL)
    assert scheduler._redis is not None, 'test requires a reachable Redis'
    return scheduler


def _names(prefix: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:12]
    return f'{prefix}_stream_{suffix}', f'{prefix}_group_{suffix}'


@pytest.mark.integration
class TestEventStreamReclaim:
    async def test_pending_entry_reclaimed_and_processed(self):
        stream, group = _names('evt_reclaim')
        bus = await _make_bus(stream, group)
        executions: list[str] = []

        async def handler(payload: EventPayload) -> None:
            executions.append('ran')

        bus._listeners['item.created'] = [(handler, 100, None)]

        try:
            assert bus._redis is not None
            await bus._redis.xadd(stream, {'event': 'item.created', 'payload': '{}'})

            # A "dead" consumer reads the message but never ACKs.
            streams = await bus._redis.xreadgroup(
                group, 'dead-consumer', {stream: '>'}, count=1
            )
            assert streams and streams[0][1], 'dead consumer must hold a pending entry'

            reclaimed = await bus.reclaim_pending_events(min_idle_ms=0)

            assert reclaimed == 1
            assert executions == ['ran']
            pending = await bus._redis.xpending(stream, group)
            assert pending['pending'] == 0
        finally:
            assert bus._redis is not None
            await bus._redis.delete(stream)
            await bus.disconnect()

    async def test_fresh_pending_entry_not_reclaimed(self):
        stream, group = _names('evt_fresh')
        bus = await _make_bus(stream, group)

        try:
            assert bus._redis is not None
            await bus._redis.xadd(stream, {'event': 'item.created', 'payload': '{}'})
            await bus._redis.xreadgroup(group, 'live-consumer', {stream: '>'}, count=1)

            # min_idle larger than the message age → nothing reclaimed.
            reclaimed = await bus.reclaim_pending_events(min_idle_ms=60_000)

            assert reclaimed == 0
            pending = await bus._redis.xpending(stream, group)
            assert pending['pending'] == 1
        finally:
            assert bus._redis is not None
            await bus._redis.delete(stream)
            await bus.disconnect()


@pytest.mark.integration
class TestTaskStreamReclaim:
    async def test_pending_task_reclaimed_and_executed(self):
        stream, group = _names('task_reclaim')
        scheduler = await _make_scheduler(stream, group)
        executions: list[str] = []

        async def handler(payload: dict | None = None) -> None:
            executions.append('ran')

        scheduler.register(
            name='t',
            interval=timedelta(hours=1),
            handler=handler,
            module_name='mod',
            is_persistent=True,
        )

        try:
            await scheduler.enqueue('mod.t')
            assert scheduler._redis is not None

            # "Dead" worker reads but never ACKs.
            streams = await scheduler._redis.xreadgroup(
                group, 'dead-worker', {stream: '>'}, count=1
            )
            assert streams and streams[0][1]

            reclaimed = await scheduler.reclaim_pending_tasks(min_idle_ms=0)

            assert reclaimed == 1
            assert executions == ['ran']
            pending = await scheduler._redis.xpending(stream, group)
            assert pending['pending'] == 0
        finally:
            assert scheduler._redis is not None
            await scheduler._redis.delete(stream)
            await scheduler._redis.aclose()


@pytest.mark.integration
class TestStreamMaxlen:
    async def test_event_stream_capped_by_maxlen(self):
        stream, group = _names('evt_maxlen')
        bus = await _make_bus(stream, group)

        try:
            with (
                patch.object(settings, 'TESTING', False),
                patch.object(settings, 'EVENT_STREAM_MAXLEN', 100),
            ):
                for _ in range(300):
                    await bus.emit(
                        'item.created', TenantEventPayload(organization_id='org-1')
                    )

            assert bus._redis is not None
            length = await bus._redis.xlen(stream)
            # Approximate trimming may overshoot the cap, never the input.
            assert length < 300
            assert length <= 200
        finally:
            assert bus._redis is not None
            await bus._redis.delete(stream)
            await bus.disconnect()

    async def test_task_stream_capped_by_maxlen(self):
        stream, group = _names('task_maxlen')
        scheduler = await _make_scheduler(stream, group)

        try:
            with patch.object(settings, 'TASK_STREAM_MAXLEN', 100):
                for _ in range(300):
                    await scheduler.enqueue('mod.t')

            assert scheduler._redis is not None
            length = await scheduler._redis.xlen(stream)
            assert length < 300
            assert length <= 200
        finally:
            assert scheduler._redis is not None
            await scheduler._redis.delete(stream)
            await scheduler._redis.aclose()


async def _consumer_names(bus: EventBus) -> set[str]:
    assert bus._redis is not None
    infos = await bus._redis.xinfo_consumers(bus._stream_name, bus._group_name)
    return {info['name'] for info in infos}


@pytest.mark.integration
class TestConsumerGroupCleanup:
    async def test_disconnect_removes_the_nodes_own_consumer(self):
        stream, group = _names('evt_leave')
        bus = await _make_bus(stream, group)
        node = bus._node_id
        # A second client to look at the group after the bus has closed.
        probe = await _make_bus(stream, group)
        try:
            assert bus._redis is not None
            await bus._redis.xadd(stream, {'event': 'x', 'payload': '{}'})
            streams = await bus._redis.xreadgroup(group, node, {stream: '>'}, count=1)
            await bus._redis.xack(stream, group, streams[0][1][0][0])
            assert node in await _consumer_names(probe)

            await bus.disconnect()

            assert node not in await _consumer_names(probe)
        finally:
            assert probe._redis is not None
            await probe._redis.delete(stream)
            await probe.disconnect()

    async def test_disconnect_keeps_a_consumer_that_still_holds_a_message(self):
        stream, group = _names('evt_leave_pending')
        bus = await _make_bus(stream, group)
        node = bus._node_id
        probe = await _make_bus(stream, group)
        try:
            assert bus._redis is not None
            await bus._redis.xadd(stream, {'event': 'x', 'payload': '{}'})
            await bus._redis.xreadgroup(group, node, {stream: '>'}, count=1)

            await bus.disconnect()

            assert node in await _consumer_names(probe)
            assert await probe.reclaim_pending_events(min_idle_ms=0) == 1
        finally:
            assert probe._redis is not None
            await probe._redis.delete(stream)
            await probe.disconnect()

    async def test_reaper_removes_dead_consumers_but_never_one_with_pending(self):
        stream, group = _names('evt_prune')
        bus = await _make_bus(stream, group)
        try:
            assert bus._redis is not None
            await bus._redis.xadd(stream, {'event': 'x', 'payload': '{}'})
            await bus._redis.xadd(stream, {'event': 'x', 'payload': '{}'})
            # One consumer read and acknowledged (empty-handed), one holds a
            # message, one only ever asked.
            first = await bus._redis.xreadgroup(group, 'gone', {stream: '>'}, count=1)
            await bus._redis.xack(stream, group, first[0][1][0][0])
            await bus._redis.xreadgroup(group, 'holding', {stream: '>'}, count=1)
            await bus._redis.xgroup_createconsumer(stream, group, 'never-read')

            removed = await bus.prune_dead_consumers(0)

            assert removed == 2
            assert await _consumer_names(bus) == {'holding'}
        finally:
            assert bus._redis is not None
            await bus._redis.delete(stream)
            await bus.disconnect()

    async def test_a_recently_active_consumer_is_left_alone(self):
        stream, group = _names('evt_prune_fresh')
        bus = await _make_bus(stream, group)
        try:
            assert bus._redis is not None
            await bus._redis.xgroup_createconsumer(stream, group, 'just-now')

            assert await bus.prune_dead_consumers(60_000) == 0
            assert await _consumer_names(bus) == {'just-now'}
        finally:
            assert bus._redis is not None
            await bus._redis.delete(stream)
            await bus.disconnect()

    async def test_scheduler_prunes_its_dead_consumers_too(self):
        stream, group = _names('task_prune')
        scheduler = await _make_scheduler(stream, group)
        try:
            assert scheduler._redis is not None
            await scheduler._redis.xgroup_createconsumer(stream, group, 'gone')

            assert await scheduler.prune_dead_consumers(0) == 1
        finally:
            assert scheduler._redis is not None
            await scheduler._redis.delete(stream)
            await scheduler._redis.aclose()
