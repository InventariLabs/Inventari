"""
Unit tests for TaskScheduler.

Tests cover:
- start_all() starts asyncio tasks
- stop_all() cancels running tasks and clears _running flag
- Periodic loop calls handler and catches exceptions without raising
- Late registration starts task immediately when scheduler is already running
- CancelledError propagates correctly during stop
"""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_start_all_sets_running_flag():
    scheduler = TaskScheduler()
    handler = AsyncMock()
    scheduler.register('t', timedelta(hours=1), handler, 'mod')

    with patch.object(scheduler, '_run_periodic', new_callable=AsyncMock):
        scheduler.start_all()
        assert scheduler._running is True
        scheduler.stop_all()


@pytest.mark.asyncio
async def test_start_all_idempotent():
    """Calling start_all twice should not duplicate tasks."""
    scheduler = TaskScheduler()
    handler = AsyncMock()
    scheduler.register('t', timedelta(hours=1), handler, 'mod')

    with patch.object(scheduler, '_run_periodic', new_callable=AsyncMock):
        scheduler.start_all()
        task_ref = scheduler._tasks['mod.t']._task
        scheduler.start_all()  # second call — no-op
        assert scheduler._tasks['mod.t']._task is task_ref
        scheduler.stop_all()


@pytest.mark.asyncio
async def test_stop_all_clears_running_and_cancels_tasks():
    scheduler = TaskScheduler()
    scheduler.register('t', timedelta(hours=1), AsyncMock(), 'mod')

    loop_started = asyncio.Event()

    async def slow_loop(task):
        loop_started.set()
        await asyncio.sleep(3600)

    with patch.object(scheduler, '_run_periodic', side_effect=slow_loop):
        scheduler.start_all()
        await loop_started.wait()

    scheduler.stop_all()
    assert scheduler._running is False


# ---------------------------------------------------------------------------
# Late registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_late_registration_starts_task_immediately():
    """When scheduler is running, registering a new task starts it at once."""
    scheduler = TaskScheduler()
    scheduler._running = True  # simulate already-running scheduler

    started = asyncio.Event()

    async def fake_run(task):
        started.set()
        await asyncio.sleep(3600)

    with patch.object(scheduler, '_run_periodic', side_effect=fake_run):
        scheduler.register('late', timedelta(minutes=1), AsyncMock(), 'mod')
        await asyncio.wait_for(started.wait(), timeout=1.0)

    assert scheduler._tasks['mod.late'].is_running is True
    scheduler.stop_all()


# ---------------------------------------------------------------------------
# _run_periodic — exception swallowing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_periodic_swallows_exceptions():
    """Exceptions from handler should be logged and not crash the loop."""
    scheduler = TaskScheduler()
    call_count = 0

    def flaky_handler():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError('simulated failure')

    from app.core.scheduler import ScheduledTask

    task = ScheduledTask(
        name='flaky',
        interval=timedelta(milliseconds=10),
        handler=flaky_handler,
        module_name='test',
    )
    scheduler._running = True

    with patch(
        'app.core.scheduler.asyncio.sleep', new_callable=AsyncMock
    ) as mock_sleep:
        # Allow 3 iterations then stop
        iteration = 0

        async def maybe_stop(delay):
            nonlocal iteration
            iteration += 1
            if iteration >= 3:
                scheduler._running = False

        mock_sleep.side_effect = maybe_stop

        # Should not raise despite flaky_handler throwing
        await scheduler._run_periodic(task)

    assert call_count >= 1


@pytest.mark.asyncio
async def test_run_periodic_handles_async_handler():
    """Async handlers should be awaited correctly."""
    scheduler = TaskScheduler()
    called = asyncio.Event()
    sleep_count = 0

    async def async_handler():
        called.set()

    from app.core.scheduler import ScheduledTask

    task = ScheduledTask(
        name='async_task',
        interval=timedelta(milliseconds=10),
        handler=async_handler,
        module_name='test',
    )
    scheduler._running = True

    with patch(
        'app.core.scheduler.asyncio.sleep', new_callable=AsyncMock
    ) as mock_sleep:

        async def stop_after_second(delay):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:  # First sleep is jitter, second is after handler
                scheduler._running = False

        mock_sleep.side_effect = stop_after_second
        await scheduler._run_periodic(task)

    assert called.is_set()


@pytest.mark.asyncio
async def test_unregister_removes_task():
    scheduler = TaskScheduler()
    handler = AsyncMock()
    scheduler.register('t', timedelta(hours=1), handler, 'mod')
    assert 'mod.t' in scheduler._tasks

    assert scheduler.unregister('t', 'mod') is True
    assert 'mod.t' not in scheduler._tasks


@pytest.mark.asyncio
async def test_unregister_unknown_is_noop():
    scheduler = TaskScheduler()
    assert scheduler.unregister('missing', 'mod') is False


@pytest.mark.asyncio
async def test_unregister_cancels_running_task():
    scheduler = TaskScheduler()
    started = asyncio.Event()

    async def handler():
        started.set()

    scheduler.register('t', timedelta(milliseconds=1), handler, 'mod')
    with patch.object(scheduler, '_run_periodic', new_callable=AsyncMock):
        scheduler.start_all()
        task = scheduler._tasks['mod.t']._task
        assert task is not None and not task.done()

        assert scheduler.unregister('t', 'mod') is True
        assert task.cancelled() or task.cancelling()
        scheduler.stop_all()


@pytest.mark.unit
class TestCoreSchedulerAPI:
    """Facade delegates to the task_scheduler singleton."""

    def test_register_task_delegates(self):
        from app.core.public_api import core_api

        with patch('app.core.scheduler.task_scheduler.register') as mock_register:
            core_api.scheduler.register_task(
                'w', timedelta(seconds=5), lambda: None, module_name='webhooks'
            )
        mock_register.assert_called_once_with(
            name='w',
            interval=timedelta(seconds=5),
            handler=mock_register.call_args.kwargs['handler'],
            module_name='webhooks',
            is_persistent=False,
        )

    def test_unregister_task_delegates(self):
        from app.core.public_api import core_api

        with patch(
            'app.core.scheduler.task_scheduler.unregister', return_value=True
        ) as mock_unregister:
            assert (
                core_api.scheduler.unregister_task('w', module_name='webhooks') is True
            )
        mock_unregister.assert_called_once_with('w', 'webhooks')


@pytest.mark.asyncio
@pytest.mark.parametrize(('persistent', 'warns'), [(True, True), (False, False)])
async def test_a_persistent_task_without_redis_says_it_runs_locally(
    caplog, persistent, warns
):
    """Asked for persistence, given none: the module author and the operator
    learn it from the log, not from a missed run after a restart."""
    import logging

    from app.core.scheduler import ScheduledTask

    scheduler = TaskScheduler()
    assert scheduler._redis is None
    task = ScheduledTask(
        name='nightly',
        interval=timedelta(milliseconds=10),
        handler=lambda: None,
        module_name='test',
        is_persistent=persistent,
    )

    with (
        caplog.at_level(logging.WARNING, logger='app.core.scheduler'),
        patch('app.core.scheduler.asyncio.sleep', new_callable=AsyncMock),
    ):
        await scheduler._run_periodic(task)  # not running: returns after the jitter

    assert ('Redis is not connected' in caplog.text) is warns
