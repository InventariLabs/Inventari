"""The E2E backend (TESTING) revokes tokens through Redis, as a deployment does.

TESTING skips the listeners and the seeding, but the token blacklist is the
one store a browser spec observes: a spent reset link must answer "spent",
and a signed-out session must stop working. Fail-open there would make those
specs pass or fail on the environment.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import _lifespan
from app.core.token_blacklist import token_blacklist


@pytest.fixture
def blacklist_restored() -> Iterator[None]:
    before = token_blacklist._redis
    try:
        yield
    finally:
        token_blacklist._redis = before


@pytest.fixture
def redis_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    monkeypatch.setattr('redis.asyncio.from_url', lambda *_a, **_k: client)
    return client


async def _start_under_testing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('app.config.settings.TESTING', True)
    await _lifespan._start_services(logging.getLogger('test'), event_bus=None)


async def test_a_reachable_redis_becomes_the_blacklist_store(
    monkeypatch: pytest.MonkeyPatch, redis_client: MagicMock, blacklist_restored: None
) -> None:
    monkeypatch.setattr('app.config.settings.TESTING_TOKEN_REVOCATION', True)
    token_blacklist._redis = None

    await _start_under_testing(monkeypatch)

    assert token_blacklist._redis is redis_client


async def test_an_unreachable_redis_leaves_the_blacklist_as_it_was(
    monkeypatch: pytest.MonkeyPatch, redis_client: MagicMock, blacklist_restored: None
) -> None:
    monkeypatch.setattr('app.config.settings.TESTING_TOKEN_REVOCATION', True)
    redis_client.ping = AsyncMock(side_effect=ConnectionError('down'))
    token_blacklist._redis = None

    await _start_under_testing(monkeypatch)

    assert token_blacklist._redis is None


async def test_the_switch_leaves_the_blacklist_alone(
    monkeypatch: pytest.MonkeyPatch, redis_client: MagicMock, blacklist_restored: None
) -> None:
    monkeypatch.setattr('app.config.settings.TESTING_TOKEN_REVOCATION', False)
    token_blacklist._redis = None

    await _start_under_testing(monkeypatch)

    assert token_blacklist._redis is None
