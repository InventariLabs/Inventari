"""Three writes into the blacklist, one rule between them.

``revoke`` and ``mark_credentials_changed`` refuse to pretend in production:
without Redis they raise, because a token that was not revoked is a token
that still works. ``revoke_user_family`` -- the write that reuse detection
makes when it catches a refresh token being replayed, which is the one moment
the system believes it is under attack -- returned quietly instead, and
logged a line at most.

Written as one parametrised case over all three so the next method added here
has to join the convention rather than quietly opt out of it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.token_blacklist import TokenBlacklist

pytestmark = pytest.mark.unit


def _expiry() -> datetime:
    # Taken at call time: an import-time value is already in the past once an
    # xdist worker has lived longer than the offset, and ``revoke`` correctly
    # skips a token that has expired, so the write these tests look for never
    # happens (a full CI run outlasts 30 minutes).
    return datetime.now(tz=UTC) + timedelta(minutes=30)


def _writes(blacklist: TokenBlacklist) -> dict[str, Callable[[], Awaitable[None]]]:
    """Every call that records "this token is no longer good"."""
    return {
        'revoke': lambda: blacklist.revoke('a.b.c', _expiry()),
        'revoke_user_family': lambda: blacklist.revoke_user_family('user-1', 's-1'),
        'mark_credentials_changed': lambda: blacklist.mark_credentials_changed(
            'user-1'
        ),
    }


_NAMES = ('revoke', 'revoke_user_family', 'mark_credentials_changed')


@pytest.mark.parametrize('write', _NAMES)
class TestInProduction:
    async def test_no_redis_at_all_is_refused(self, write: str) -> None:
        blacklist = TokenBlacklist()
        with patch.object(TokenBlacklist, '_fail_closed', return_value=True):
            with pytest.raises(RuntimeError):
                await _writes(blacklist)[write]()

    async def test_a_redis_that_fails_mid_write_is_refused(self, write: str) -> None:
        blacklist = TokenBlacklist()
        redis = AsyncMock()
        # ``revoke`` writes with SET NX (it must not overwrite an existing
        # revocation time); the other two still use SETEX.
        redis.set = AsyncMock(side_effect=RedisConnectionError('down'))
        redis.setex = AsyncMock(side_effect=RedisConnectionError('down'))
        blacklist.set_redis(redis)

        with patch.object(TokenBlacklist, '_fail_closed', return_value=True):
            with pytest.raises(RuntimeError):
                await _writes(blacklist)[write]()


@pytest.mark.parametrize('write', _NAMES)
class TestInDevelopment:
    async def test_it_carries_on_without_redis(self, write: str) -> None:
        """The control: a developer's laptop has no Redis and must still run."""
        blacklist = TokenBlacklist()
        with patch.object(TokenBlacklist, '_fail_closed', return_value=False):
            await _writes(blacklist)[write]()


@pytest.mark.parametrize('write', _NAMES)
class TestTheHappyPath:
    async def test_the_marker_is_written(self, write: str) -> None:
        blacklist = TokenBlacklist()
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.setex = AsyncMock(return_value=True)
        blacklist.set_redis(redis)

        await _writes(blacklist)[write]()

        writer = redis.set if write == 'revoke' else redis.setex
        writer.assert_called_once()
