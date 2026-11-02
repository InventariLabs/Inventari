"""The acknowledgement has to come after the handlers, not before them.

The consumer loop called ``_handle_stream_message`` and acknowledged on the
next line. That would have been correct if the dispatch had run the
handlers — outside tests it did not: ``_execute_local`` handed each handler
to ``asyncio.create_task`` and returned, so the message was acknowledged
while no handler had started. A worker that died in that window left
nothing pending, and ``reclaim_pending_events`` — the whole redelivery
mechanism — had nothing to find. The docstring called this "exactly once".

Everything here runs against a real Redis stream with a consumer group of
its own, and reads Redis's own pending-entries list rather than trusting
the bus's account of itself.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core import _event_bus as bus_module
from app.core._event_bus import EventBus
from app.core._event_types import EventPayload, TenantEventPayload

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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


async def _make_bus() -> EventBus:
    bus = EventBus()
    bus._stream_name = f'test_stream_{uuid.uuid4().hex[:12]}'
    bus._group_name = f'test_group_{uuid.uuid4().hex[:12]}'
    await bus.connect(settings.REDIS_URL)
    assert bus._redis is not None, 'test requires a reachable Redis'
    return bus


async def _pending_count(bus: EventBus) -> int:
    """How many messages this group has read but not acknowledged."""
    assert bus._redis is not None
    summary = await bus._redis.xpending(bus._stream_name, bus._group_name)
    # redis-py returns a dict for the summary form.
    return int(summary['pending'] if isinstance(summary, dict) else summary[0])


async def _cleanup(bus: EventBus) -> None:
    # Several of these tests disconnect as the thing under test, which
    # closes the client — reconnect rather than leave the stream behind on
    # a shared Redis.
    if bus._redis is None:
        await bus.connect(settings.REDIS_URL)
    if bus._redis is not None:
        await bus._redis.delete(bus._stream_name)
    await bus.disconnect()


class TestACrashMidHandler:
    async def test_the_message_is_still_pending(self):
        """Killed inside a handler, the event comes back to be reclaimed."""
        bus = await _make_bus()
        entered = asyncio.Event()

        async def never_finishes(payload: EventPayload) -> None:
            entered.set()
            await asyncio.sleep(60)

        bus._listeners['item.created'] = [(never_finishes, 100, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await bus.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )
                listener = asyncio.create_task(bus.listen())
                await asyncio.wait_for(entered.wait(), timeout=5)
                # The crash: the worker dies while the handler is mid-flight.
                listener.cancel()
                # The loop catches the cancellation and breaks, so awaiting
                # it returns rather than raising -- what matters is that it
                # never reached the xack.
                await listener

            assert await _pending_count(bus) == 1
        finally:
            await _cleanup(bus)

    async def test_reclaim_runs_the_handler_again(self):
        """Which is what the pending entry is for."""
        bus = await _make_bus()
        entered = asyncio.Event()
        runs: list[str] = []

        async def stalls_once(payload: EventPayload) -> None:
            runs.append('run')
            if len(runs) == 1:
                entered.set()
                await asyncio.sleep(60)

        bus._listeners['item.created'] = [(stalls_once, 100, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await bus.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )
                listener = asyncio.create_task(bus.listen())
                await asyncio.wait_for(entered.wait(), timeout=5)
                listener.cancel()
                # The loop catches the cancellation and breaks, so awaiting
                # it returns rather than raising -- what matters is that it
                # never reached the xack.
                await listener

                reclaimed = await bus.reclaim_pending_events(min_idle_ms=0)

            assert reclaimed == 1
            assert runs == ['run', 'run']
            assert await _pending_count(bus) == 0
        finally:
            await _cleanup(bus)


class TestAHandlerThatFinishes:
    async def test_nothing_is_left_pending(self):
        bus = await _make_bus()
        done = asyncio.Event()

        async def handler(payload: EventPayload) -> None:
            done.set()

        bus._listeners['item.created'] = [(handler, 100, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await bus.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )
                listener = asyncio.create_task(bus.listen())
                await asyncio.wait_for(done.wait(), timeout=5)
                await asyncio.sleep(0.1)
                await bus.disconnect()
                listener.cancel()

            bus._redis = None
            await bus.connect(settings.REDIS_URL)
            assert await _pending_count(bus) == 0
        finally:
            await _cleanup(bus)


class TestDisconnect:
    async def test_it_waits_for_a_running_handler(self):
        """Shutdown used to return while handlers were still in flight."""
        bus = await _make_bus()
        entered = asyncio.Event()
        finished: list[str] = []

        async def slow(payload: EventPayload) -> None:
            entered.set()
            await asyncio.sleep(0.4)
            finished.append('done')

        bus._listeners['item.created'] = [(slow, 100, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await bus.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )
                await bus.start_listener()
                await asyncio.wait_for(entered.wait(), timeout=5)

                await bus.disconnect()

            assert finished == ['done'], 'disconnect returned mid-handler'
        finally:
            await _cleanup(bus)

    async def test_a_stuck_handler_does_not_hold_the_shutdown(self, monkeypatch):
        """And what it was holding stays pending, to be redelivered."""
        monkeypatch.setattr(bus_module, 'SHUTDOWN_DRAIN_S', 0.2)
        bus = await _make_bus()
        entered = asyncio.Event()

        async def never_finishes(payload: EventPayload) -> None:
            entered.set()
            await asyncio.sleep(60)

        bus._listeners['item.created'] = [(never_finishes, 100, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await bus.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )
                await bus.start_listener()
                await asyncio.wait_for(entered.wait(), timeout=5)

                await asyncio.wait_for(bus.disconnect(), timeout=5)

            await bus.connect(settings.REDIS_URL)
            assert await _pending_count(bus) == 1
        finally:
            await _cleanup(bus)


class TestAHandlerThatNeverReturns:
    async def test_it_does_not_stall_the_loop_forever(self, monkeypatch):
        """The bound is what keeps one bad handler from freezing the node."""
        monkeypatch.setattr(bus_module, 'HANDLER_TIMEOUT_S', 0.2)
        bus = await _make_bus()
        order: list[str] = []
        second_ran = asyncio.Event()

        async def stalls(payload: EventPayload) -> None:
            order.append('stalls')
            await asyncio.sleep(60)

        async def after(payload: EventPayload) -> None:
            order.append('after')
            second_ran.set()

        bus._listeners['item.created'] = [(stalls, 100, None), (after, 200, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await bus.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )
                listener = asyncio.create_task(bus.listen())
                # Wait for the second handler instead of a fixed window: the
                # test fails only when it never runs, however loaded the host.
                await asyncio.wait_for(second_ran.wait(), timeout=30)
                listener.cancel()
                # The loop catches the cancellation and breaks, so awaiting
                # it returns rather than raising -- what matters is that it
                # never reached the xack.
                await listener

            # The second handler ran, so the first was abandoned rather than
            # allowed to hold the loop.
            assert order == ['stalls', 'after']
        finally:
            await _cleanup(bus)
