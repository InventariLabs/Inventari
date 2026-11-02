"""A handler approaching the fuse has to be visible before it is dropped.

``_run_handler`` abandons a handler that outlasts ``HANDLER_TIMEOUT_S``, and
the log said so — at the moment of abandonment, and not a moment earlier.
Everything from the first second up to the bound itself was silent: a
handler hovering at 29 s looked exactly like one that returned in ten
milliseconds. Because handlers run in sequence, one slow subscriber pushed
the whole node to ~30 s per event with no advance notice at all, and the
abandonment was also the first line that named the event.

The warning now arrives halfway to the bound, while the handler still runs,
and names both the handler and the event. The abandonment is not a retry:
the handler is dropped and the message is acknowledged anyway, so for a
handler that slow the delivery guarantee inverts to at-most-once — the
warning is the only notice before the event is lost to it.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.core import _event_bus as event_bus_module
from app.core._event_bus import EventBus
from app.core.contracts import EventPayload

pytestmark = pytest.mark.unit


async def _wait_for_warning(caplog: pytest.LogCaptureFixture) -> None:
    for _ in range(200):
        if any(r.levelno == logging.WARNING for r in caplog.records):
            return
        await asyncio.sleep(0.01)
    pytest.fail('no warning arrived while the handler was still running')


@pytest.mark.unit
class TestAHandlerApproachingTheBound:
    async def test_the_warning_arrives_before_the_handler_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(event_bus_module, 'HANDLER_TIMEOUT_S', 0.4)
        bus = EventBus()
        entered = asyncio.Event()
        release = asyncio.Event()
        finished: list[str] = []

        async def stalling(payload: EventPayload) -> None:
            entered.set()
            await release.wait()
            finished.append('finished')

        bus._listeners['item.created'] = [(stalling, 100, None)]

        with caplog.at_level(logging.WARNING, logger='app.core._event_bus'):
            run = asyncio.create_task(
                bus._execute_local('item.created', payload=EventPayload())
            )
            await asyncio.wait_for(entered.wait(), timeout=5)
            # The handler is only released by the test, and it is not: the
            # warning below has to appear while the handler is still running,
            # with the fuse — not the test — being what ends it.
            await asyncio.wait_for(_wait_for_warning(caplog), timeout=5)
            assert not run.done(), 'the handler finished before the warning'
            await asyncio.wait_for(run, timeout=5)

        records = [r for r in caplog.records if r.name == 'app.core._event_bus']
        assert [r.levelname for r in records] == ['WARNING', 'ERROR']
        assert 'stalling' in records[0].getMessage()
        assert 'item.created' in records[0].getMessage()
        assert 'item.created' in records[1].getMessage()
        assert finished == [], 'the handler outlived the fuse'


@pytest.mark.unit
class TestAHandlerInsideTheBound:
    async def test_it_logs_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The control: the notice must not fire for a handler that keeps up."""
        monkeypatch.setattr(event_bus_module, 'HANDLER_TIMEOUT_S', 5.0)
        bus = EventBus()
        ran: list[str] = []

        async def quick(payload: EventPayload) -> None:
            ran.append('quick')

        bus._listeners['item.created'] = [(quick, 100, None)]

        with caplog.at_level(logging.WARNING, logger='app.core._event_bus'):
            await bus._execute_local('item.created', payload=EventPayload())

        assert ran == ['quick']
        assert caplog.records == []
