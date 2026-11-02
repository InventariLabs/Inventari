"""Unit tests for TokenBlacklist."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.token_blacklist import TokenBlacklist

TOKEN = 'eyJhbGciOiJIUzI1NiJ9.test.token'
FUTURE_EXPIRY = datetime.now(tz=UTC) + timedelta(minutes=30)
PAST_EXPIRY = datetime.now(tz=UTC) - timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blacklist_with_redis():
    """Return a TokenBlacklist with a mocked async Redis client."""
    bl = TokenBlacklist()
    redis_mock = AsyncMock()
    # revoke() writes with SET NX so a second revocation of the same token
    # keeps the first timestamp; the other writers still use SETEX.
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.setex = AsyncMock(return_value=True)
    redis_mock.exists = AsyncMock(return_value=0)
    bl.set_redis(redis_mock)
    return bl, redis_mock


# ---------------------------------------------------------------------------
# revoke()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_stores_token_in_redis():
    """revoke() must write the key with a positive TTL, and not overwrite."""
    bl, redis_mock = _blacklist_with_redis()
    await bl.revoke(TOKEN, FUTURE_EXPIRY)

    redis_mock.set.assert_called_once()
    (key, value), kwargs = redis_mock.set.call_args
    assert key == f'token_blacklist:{TOKEN}'
    assert kwargs['ex'] > 0
    assert kwargs['nx'] is True
    int(value)  # must be a valid unix timestamp string


@pytest.mark.asyncio
async def test_revoke_skips_already_expired_token():
    """revoke() must NOT write anything if the token is already expired."""
    bl, redis_mock = _blacklist_with_redis()
    await bl.revoke(TOKEN, PAST_EXPIRY)

    redis_mock.set.assert_not_called()


@pytest.mark.asyncio
async def test_revoke_without_redis_does_not_raise():
    """revoke() without Redis set must log and return gracefully (fail-open)."""
    bl = TokenBlacklist()  # No Redis injected
    # Should not raise any exception
    await bl.revoke(TOKEN, FUTURE_EXPIRY)


# ---------------------------------------------------------------------------
# is_revoked()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_revoked_returns_true_for_blacklisted_token():
    """is_revoked() returns True when Redis has the key."""
    bl, redis_mock = _blacklist_with_redis()
    redis_mock.exists = AsyncMock(return_value=1)

    result = await bl.is_revoked(TOKEN)

    assert result is True
    redis_mock.exists.assert_called_once_with(f'token_blacklist:{TOKEN}')


@pytest.mark.asyncio
async def test_is_revoked_returns_false_for_clean_token():
    """is_revoked() returns False when token is not in Redis."""
    bl, redis_mock = _blacklist_with_redis()
    redis_mock.exists = AsyncMock(return_value=0)

    result = await bl.is_revoked(TOKEN)

    assert result is False


@pytest.mark.asyncio
async def test_is_revoked_returns_false_when_redis_unavailable():
    """is_revoked() returns False (fail-open) when Redis is not connected."""
    bl = TokenBlacklist()  # No Redis injected

    result = await bl.is_revoked(TOKEN)

    assert result is False


@pytest.mark.asyncio
async def test_is_revoked_without_redis_warns_only_once(caplog):
    """Fail-open mode must not spam the logs on every request (E2E noise)."""
    import logging

    bl = TokenBlacklist()  # No Redis injected

    with caplog.at_level(logging.WARNING, logger='app.core.token_blacklist'):
        await bl.is_revoked(TOKEN)
        await bl.is_revoked(TOKEN)
        await bl.is_revoked(TOKEN)

    warnings = [r for r in caplog.records if 'skipping revocation check' in r.message]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_warn_once_flag_resets_when_redis_is_injected(caplog):
    """If Redis disappears again after set_redis, the warning fires anew."""
    import logging

    bl, _redis_mock = _blacklist_with_redis()
    bl._redis = None  # simulate connection loss after startup

    with caplog.at_level(logging.WARNING, logger='app.core.token_blacklist'):
        await bl.is_revoked(TOKEN)
        bl.set_redis(AsyncMock())
        bl._redis = None
        await bl.is_revoked(TOKEN)

    warnings = [r for r in caplog.records if 'skipping revocation check' in r.message]
    assert len(warnings) == 2


@pytest.mark.asyncio
async def test_is_revoked_returns_false_on_redis_error():
    """is_revoked() returns False (fail-open) when Redis raises an exception."""
    bl, redis_mock = _blacklist_with_redis()
    redis_mock.exists = AsyncMock(side_effect=RedisConnectionError('Redis down'))

    result = await bl.is_revoked(TOKEN)

    assert result is False


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_then_is_revoked():
    """After revoking a token, is_revoked() must return True."""
    bl, redis_mock = _blacklist_with_redis()

    # Simulate that after setex the key exists
    async def exists_side_effect(key):
        return 1 if 'blacklist' in key else 0

    redis_mock.exists = AsyncMock(side_effect=exists_side_effect)

    await bl.revoke(TOKEN, FUTURE_EXPIRY)
    result = await bl.is_revoked(TOKEN)

    assert result is True


# ---------------------------------------------------------------------------
# mark_credentials_changed() / is_issued_before_credential_change()
# ---------------------------------------------------------------------------


def _blacklist_with_store():
    """TokenBlacklist over a tiny in-memory Redis stand-in."""
    from tests.integration._fake_token_store import FakeTokenStore

    bl = TokenBlacklist()
    fake = FakeTokenStore()
    bl.set_redis(fake)  # type: ignore[arg-type]
    return bl, fake


@pytest.mark.asyncio
async def test_no_marker_means_no_token_is_stale():
    bl, _ = _blacklist_with_store()

    assert await bl.is_issued_before_credential_change('user-1', 1_000) is False


@pytest.mark.asyncio
async def test_token_issued_before_credential_change_is_stale():
    bl, fake = _blacklist_with_store()

    await bl.mark_credentials_changed('user-1')
    marker = float(fake.store[f'{bl.PREFIX}credchg:user-1'])

    assert (
        await bl.is_issued_before_credential_change('user-1', int(marker) - 5) is True
    )


@pytest.mark.asyncio
async def test_token_issued_after_credential_change_survives():
    bl, fake = _blacklist_with_store()

    await bl.mark_credentials_changed('user-1')
    marker = float(fake.store[f'{bl.PREFIX}credchg:user-1'])

    assert (
        await bl.is_issued_before_credential_change('user-1', int(marker) + 5) is False
    )


@pytest.mark.asyncio
async def test_marker_is_scoped_to_one_user():
    bl, fake = _blacklist_with_store()

    await bl.mark_credentials_changed('user-1')
    marker = float(fake.store[f'{bl.PREFIX}credchg:user-1'])

    assert (
        await bl.is_issued_before_credential_change('user-2', int(marker) - 5) is False
    )


@pytest.mark.asyncio
async def test_token_without_iat_counts_as_stale():
    """Tokens minted before this mechanism existed carry no ``iat``."""
    bl, _ = _blacklist_with_store()

    await bl.mark_credentials_changed('user-1')

    assert await bl.is_issued_before_credential_change('user-1', None) is True


# ---------------------------------------------------------------------------
# The credential-change marker must fail closed in production
# ---------------------------------------------------------------------------


@pytest.fixture
def production_mode(monkeypatch):
    """Make ``_fail_closed()`` report production."""
    from app.config import settings

    monkeypatch.setattr(settings, 'DEBUG', False)
    monkeypatch.setattr(settings, 'TESTING', False)
    monkeypatch.delenv('TESTING', raising=False)


@pytest.mark.asyncio
async def test_marker_check_denies_without_redis_in_production(production_mode):
    """A Redis outage must not resurrect sessions a reset killed."""
    bl = TokenBlacklist()  # no Redis injected

    assert await bl.is_issued_before_credential_change('user-1', 1_000) is True


@pytest.mark.asyncio
async def test_marker_check_denies_on_redis_error_in_production(production_mode):
    bl, redis_mock = _blacklist_with_redis()
    redis_mock.get = AsyncMock(side_effect=RedisConnectionError('Redis down'))

    assert await bl.is_issued_before_credential_change('user-1', 1_000) is True


@pytest.mark.asyncio
async def test_corrupted_marker_denies_in_production(production_mode):
    bl, fake = _blacklist_with_store()
    fake.store[f'{bl.PREFIX}credchg:user-1'] = 'not-a-timestamp'

    assert await bl.is_issued_before_credential_change('user-1', 1_000) is True


@pytest.mark.asyncio
async def test_readable_absent_marker_still_allows_in_production(production_mode):
    """Only an *unreadable* store denies — a clean store must not lock users out."""
    bl, _ = _blacklist_with_store()

    assert await bl.is_issued_before_credential_change('user-1', 1_000) is False


@pytest.mark.asyncio
async def test_marker_check_stays_fail_open_in_dev():
    """Dev/test mode keeps working without Redis."""
    bl = TokenBlacklist()

    assert await bl.is_issued_before_credential_change('user-1', 1_000) is False


@pytest.mark.asyncio
async def test_mark_credentials_changed_raises_without_redis_in_production(
    production_mode,
):
    """Silently skipping the write would report a reset that did not happen."""
    bl = TokenBlacklist()

    with pytest.raises(RuntimeError, match='credential change'):
        await bl.mark_credentials_changed('user-1')


@pytest.mark.asyncio
async def test_mark_credentials_changed_raises_on_redis_error_in_production(
    production_mode,
):
    bl, redis_mock = _blacklist_with_redis()
    redis_mock.setex = AsyncMock(side_effect=RedisConnectionError('Redis down'))

    with pytest.raises(RuntimeError, match='credential change'):
        await bl.mark_credentials_changed('user-1')


@pytest.mark.asyncio
async def test_mark_credentials_changed_stays_quiet_in_dev():
    bl = TokenBlacklist()

    await bl.mark_credentials_changed('user-1')  # must not raise


@pytest.mark.asyncio
async def test_is_user_revoked_fails_closed_in_production(production_mode):
    """Reuse detection reads this marker — fail-open would replay tokens."""
    bl = TokenBlacklist()

    assert await bl.is_user_revoked('user-1', 'session-1') is True


@pytest.mark.asyncio
async def test_is_user_revoked_fails_closed_on_redis_error(production_mode):
    bl, redis_mock = _blacklist_with_redis()
    redis_mock.exists = AsyncMock(side_effect=RedisConnectionError('Redis down'))

    assert await bl.is_user_revoked('user-1', 'session-1') is True
