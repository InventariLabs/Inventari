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
