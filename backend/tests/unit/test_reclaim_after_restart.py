"""The stream reaper runs once at startup, not only on its first tick."""

from unittest.mock import AsyncMock, MagicMock, patch

from redis.exceptions import ConnectionError as RedisConnectionError

from app._lifespan import _reclaim_after_restart


def _services(*, connected: bool) -> tuple[MagicMock, MagicMock]:
    bus = MagicMock()
    bus.redis = object() if connected else None
    scheduler = MagicMock()
    scheduler._redis = None
    return bus, scheduler


async def test_reaper_runs_once_when_redis_is_connected():
    bus, scheduler = _services(connected=True)
    with patch('app.core.stream_reaper.reap_streams_once', AsyncMock()) as reap:
        await _reclaim_after_restart(MagicMock(), bus, scheduler)
    reap.assert_awaited_once()


async def test_nothing_runs_without_redis():
    bus, scheduler = _services(connected=False)
    with patch('app.core.stream_reaper.reap_streams_once', AsyncMock()) as reap:
        await _reclaim_after_restart(MagicMock(), bus, scheduler)
    reap.assert_not_awaited()


async def test_a_redis_failure_does_not_stop_startup():
    bus, scheduler = _services(connected=True)
    logger = MagicMock()
    with patch(
        'app.core.stream_reaper.reap_streams_once',
        AsyncMock(side_effect=RedisConnectionError('down')),
    ):
        await _reclaim_after_restart(logger, bus, scheduler)
    logger.warning.assert_called_once()


async def test_an_unexpected_error_is_logged_and_does_not_stop_startup():
    """The tick survives any exception from the same call; so must startup."""
    bus, scheduler = _services(connected=True)
    logger = MagicMock()
    with patch(
        'app.core.stream_reaper.reap_streams_once',
        AsyncMock(side_effect=ValueError('malformed task payload')),
    ):
        await _reclaim_after_restart(logger, bus, scheduler)
    logger.warning.assert_called_once()


def _startup_steps(calls: list[str], *, reclaim_error: Exception | None = None):
    """Patch every step of ``_start_services`` and record the order they ran."""

    def step(name: str, result=None, error: Exception | None = None):
        async def run(*_args, **_kwargs):
            calls.append(name)
            if error is not None:
                raise error
            return result

        return run

    def register(*_args, **_kwargs):
        calls.append('register_jobs')

    def guard():
        calls.append('dev_guard')

    redis_bus = MagicMock()
    redis_bus.redis = object()
    return redis_bus, [
        patch('app._lifespan._connect_redis_services', step('connect', 'hub')),
        patch('app._lifespan._wire_token_blacklist_and_cache', step('wire')),
        patch('app._lifespan._seed_and_bootstrap', step('seed')),
        patch('app._lifespan._initialize_modules', step('modules', ['broken'])),
        patch('app._lifespan._register_background_jobs', register),
        patch(
            'app.core.stream_reaper.reap_streams_once',
            step('reap', None, reclaim_error),
        ),
        patch('app.core.dev_guard.run_dev_guard', guard),
        patch('app.config.settings.TESTING', False),
    ]


async def _run_startup(calls: list[str], *, reclaim_error: Exception | None = None):
    from contextlib import ExitStack

    from app._lifespan import _start_services

    bus, patches = _startup_steps(calls, reclaim_error=reclaim_error)
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        # The reclaim needs a Redis-backed bus; the scheduler singleton has none.
        return await _start_services(MagicMock(), bus)


async def test_startup_runs_the_reaper_once_after_the_modules_initialised():
    calls: list[str] = []
    await _run_startup(calls)
    assert calls.count('reap') == 1
    assert calls.index('modules') < calls.index('register_jobs') < calls.index('reap')


async def test_a_failing_reclaim_still_reaches_the_dev_guard_and_returns_failed_modules():
    calls: list[str] = []
    hub, failed = await _run_startup(calls, reclaim_error=ValueError('bad payload'))
    assert 'dev_guard' in calls
    assert calls.index('reap') < calls.index('dev_guard')
    assert (hub, failed) == ('hub', ['broken'])
