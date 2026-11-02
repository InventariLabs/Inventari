"""Integration tests for the Redis-backed cache layer.

Verifies that ``cache_get_or_set`` returns cached values on the second
call (factory invoked only once) and that analytics caching is versioned:
``org_query_key`` names the organization's current version, and
``cache_invalidate_org_queries`` invalidates by bumping it — one command,
whether the keyspace holds three keys or three thousand.

Tests use an in-memory fake Redis so the suite does not depend on a
running Redis instance.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_module
from app.core.contracts import OverviewDTO
from app.core.public_api import core_api
from tests.integration._fake_redis import FakeRedis

pytestmark = pytest.mark.integration

ORG_A = UUID('00000000-0000-0000-0000-00000000000a')
ORG_B = UUID('00000000-0000-0000-0000-00000000000b')


class _DownRedis:
    """A Redis that answers every command with a connection error."""

    async def get(self, key: str) -> str | None:
        raise ConnectionError('redis is down')

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        raise ConnectionError('redis is down')

    async def incr(self, key: str) -> int:
        raise ConnectionError('redis is down')


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """In-memory Redis replacement, installed for the duration of the test."""
    redis = FakeRedis()
    monkeypatch.setattr(cache_module, '_redis', redis)
    return redis


async def test_cache_get_or_set_invokes_factory_only_on_miss(
    fake_redis: FakeRedis,
    real_async_db_session: AsyncSession,
    async_test_storage_location,
):
    """First call: factory runs. Second call: cached value, factory skipped."""
    factory_calls = 0

    async def _factory() -> dict[str, Any]:
        nonlocal factory_calls
        factory_calls += 1
        return {'computed': True}

    result_1 = await cache_module.cache_get_or_set('k1', ttl=60, factory=_factory)
    result_2 = await cache_module.cache_get_or_set('k1', ttl=60, factory=_factory)

    assert result_1 == {'computed': True}
    assert result_2 == {'computed': True}
    assert factory_calls == 1, 'second call must be served from cache'


async def test_cache_get_or_set_falls_through_without_redis(
    monkeypatch: pytest.MonkeyPatch,
    real_async_db_session: AsyncSession,
    async_test_storage_location,
):
    """When _redis is None, factory is invoked every call (no caching)."""
    monkeypatch.setattr(cache_module, '_redis', None)

    factory_calls = 0

    async def _factory() -> int:
        nonlocal factory_calls
        factory_calls += 1
        return 42

    await cache_module.cache_get_or_set('k1', ttl=60, factory=_factory)
    await cache_module.cache_get_or_set('k1', ttl=60, factory=_factory)

    assert factory_calls == 2, 'without Redis, every call must hit factory'


async def test_org_query_key_names_the_orgs_current_version(
    fake_redis: FakeRedis,
) -> None:
    """A query key carries the org's version, so a bump renames every entry."""
    assert await cache_module.org_query_key(ORG_A, 'overview') == (
        f'org:{ORG_A}:query:v0:overview'
    )

    await fake_redis.incr(cache_module.org_query_version_key(ORG_A))

    assert await cache_module.org_query_key(ORG_A, 'overview') == (
        f'org:{ORG_A}:query:v1:overview'
    )
    # A second org's counter is its own.
    assert await cache_module.org_query_key(ORG_B, 'overview') == (
        f'org:{ORG_B}:query:v0:overview'
    )


async def test_org_query_key_without_redis_is_version_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Redis configured: the key still exists, it just names version 0."""
    monkeypatch.setattr(cache_module, '_redis', None)
    assert await cache_module.org_query_key(ORG_A, 'overview') == (
        f'org:{ORG_A}:query:v0:overview'
    )


async def test_invalidation_costs_one_command_whatever_the_keyspace_holds(
    fake_redis: FakeRedis,
) -> None:
    """The price of invalidation does not grow with the key count."""
    fake_redis.commands.clear()
    await cache_module.cache_invalidate_org_queries(ORG_A)
    on_an_empty_keyspace = list(fake_redis.commands)

    # Cached answers of another organization, plus everything else an
    # installation keeps in the same Redis — the keys the old SCAN walked
    # before it reached this org's two entries.
    for i in range(2000):
        await fake_redis.set(f'org:{ORG_B}:query:v0:name{i}', '{}')
        await fake_redis.set(f'unrelated:{i}', '{}')

    fake_redis.commands.clear()
    await cache_module.cache_invalidate_org_queries(ORG_A)

    assert fake_redis.commands == on_an_empty_keyspace == ['incr'], (
        'invalidation must cost one command, not a walk over the keyspace'
    )
    # Two bumps: the version is the org's own, and it moved.
    assert await fake_redis.get(cache_module.org_query_version_key(ORG_A)) == '2'
    assert await fake_redis.get(cache_module.org_query_version_key(ORG_B)) is None, (
        'another organization must not be invalidated'
    )


async def test_invalidation_orphans_this_orgs_entry_and_leaves_the_others(
    fake_redis: FakeRedis,
) -> None:
    """Reachability, not deletion: the old key is left to its own TTL."""
    stale_key = await cache_module.org_query_key(ORG_A, 'overview')
    foreign_key = await cache_module.org_query_key(ORG_B, 'overview')
    await fake_redis.set(stale_key, json.dumps({'total_items': 2}))
    await fake_redis.set(foreign_key, json.dumps({'total_items': 7}))

    await cache_module.cache_invalidate_org_queries(ORG_A)

    current_key = await cache_module.org_query_key(ORG_A, 'overview')
    assert current_key != stale_key
    assert await fake_redis.get(current_key) is None, 'the next read must recompute'
    assert await fake_redis.get(foreign_key) == json.dumps({'total_items': 7}), (
        "another org's cached answer must still be reachable"
    )
    # Nobody deletes the orphan — that delete is what grew with the keyspace.
    assert await fake_redis.get(stale_key) == json.dumps({'total_items': 2})


async def test_invalidation_without_redis_is_a_silent_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Redis, invalidation does nothing and raises nothing."""
    monkeypatch.setattr(cache_module, '_redis', None)
    assert await cache_module.cache_invalidate_org_queries(ORG_A) is None


async def test_a_down_redis_costs_a_recomputation_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every cache access is guarded: a Redis outage degrades, never raises."""
    monkeypatch.setattr(cache_module, '_redis', _DownRedis())

    key = await cache_module.org_query_key(ORG_A, 'overview')
    assert key == f'org:{ORG_A}:query:v0:overview', (
        'an unreadable version must degrade to zero, not to an exception'
    )

    factory_calls = 0

    async def _factory() -> int:
        nonlocal factory_calls
        factory_calls += 1
        return 42

    assert await cache_module.cache_get_or_set(key, ttl=60, factory=_factory) == 42
    assert factory_calls == 1
    assert await cache_module.cache_invalidate_org_queries(ORG_A) is None


async def test_core_api_overview_caches_under_the_versioned_org_key(
    fake_redis: FakeRedis,
    real_async_db_session: AsyncSession,
    async_test_storage_location,
):
    """core_api.queries.get_overview_async caches results per (org, version)."""
    org_id = async_test_storage_location.organization_id

    a = await core_api.queries.get_overview_async(real_async_db_session, org_id)
    b = await core_api.queries.get_overview_async(real_async_db_session, org_id)

    assert isinstance(a, OverviewDTO), 'cached value must round-trip to OverviewDTO'
    assert a == b, 'second call must return identical DTO from cache'

    assert await fake_redis.get(f'org:{org_id}:query:v0:overview') is not None

    await cache_module.cache_invalidate_org_queries(org_id)
    await core_api.queries.get_overview_async(real_async_db_session, org_id)

    assert await fake_redis.get(f'org:{org_id}:query:v1:overview') is not None, (
        'after a bump the read must resolve the new version and cache there'
    )
