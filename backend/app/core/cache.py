"""Simple Redis-backed cache helper for rarely-changing endpoints.

Usage::

    from app.core.cache import cache_get_or_set, cache_delete

    # In endpoint:
    data = await cache_get_or_set(
        'org:{org_id}:modules', ttl=300, factory=lambda: compute_modules(org_id)
    )

    # On write (invalidate):
    await cache_delete(f'org:{org_id}:modules')

Analytics read-models invalidate differently: they are many keys whose names
depend on a per-organization version counter, and dropping one version's
worth of them costs a single ``INCR`` — see :func:`org_query_key` and
:func:`cache_invalidate_org_queries`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis as RedisClient

logger = get_logger(__name__)

_redis: RedisClient | None = None


def set_cache_redis(redis_instance: RedisClient) -> None:
    """Inject the Redis connection (called during app startup)."""
    global _redis
    _redis = redis_instance


def org_query_version_key(org_id: UUID) -> str:
    """Cache key holding *org_id*'s current analytics query version.

    One small counter per organization, written only by
    :func:`cache_invalidate_org_queries`. It carries no TTL on purpose: an
    expired counter would restart at an older number, and a cache entry
    written under that number could then be found again.

    Losing the counter to *eviction* does the same thing, and cannot be ruled
    out: Redis runs ``allkeys-lru`` (docker-compose.yml, docker-compose.prod.yml),
    which evicts keys that have no TTL too. The loss is accepted rather than
    prevented, because it is bounded: every entry written under an old number
    dies on its own TTL (300 s for the analytics read-models), so the worst
    case is an answer up to one TTL stale -- exactly the staleness the cache
    already tolerates when nothing invalidates it at all -- and the counter is
    read on every analytics request, which keeps it the hottest key of its
    organization. Moving it to ``redis-critical`` (``noeviction``) would remove
    the case entirely, at the price of a second connection on the read path.
    """
    return f'org:{org_id}:query_version'


async def _org_query_version(org_id: UUID) -> int:
    """Version to name *org_id*'s analytics cache entries with; 0 if unknown.

    Unknown means "no Redis configured" or "nothing has invalidated this org
    yet" — the caller only needs a key, and both answer it the same way. A
    version that cannot be *read* is also unknown: the read is guarded like
    every other cache access, because a Redis hiccup must degrade a query to
    recomputing, never to an error.
    """
    if _redis is None:
        return 0
    try:
        raw = await _redis.get(org_query_version_key(org_id))
    except Exception:  # noqa: BLE001 — cache read must never break the endpoint
        logger.debug('Cache version read failed for org %s', org_id)
        return 0
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.debug('Cache version for org %s is not a number: %r', org_id, raw)
        return 0


async def org_query_key(org_id: UUID, query_name: str) -> str:
    """Build the canonical cache key for a per-organization analytics query.

    The entry is named after the organization's *current* query version —
    ``org:{org_id}:query:v{n}:{query_name}`` — which is what lets
    invalidation bump one counter instead of hunting for the keys.

    Async because the version lives in Redis: a read now costs one extra
    ``GET`` (this one) and in exchange an invalidation costs one ``INCR``
    instead of a walk over the keyspace. Entries written under an older
    version are never deleted; they become unreachable and expire on their
    own TTL (300 s for the analytics read-models). That is the price of a
    constant-cost invalidation, and the TTL is what bounds it.
    """
    version = await _org_query_version(org_id)
    return f'org:{org_id}:query:v{version}:{query_name}'


def _serialize(value: Any) -> str:
    """JSON-encode *value*, transparently handling Pydantic models.

    Lists of models use ``mode='json'``: plain ``model_dump()`` leaves UUIDs
    and datetimes as Python objects, so ``json.dumps`` raised TypeError. The
    write is wrapped in a try/except by design — a cache failure must not break
    an endpoint — which meant the error was swallowed and the cache simply
    never populated. Every request recomputed, silently, and the only trace was
    a debug line.

    ``default=str`` is the backstop for anything else non-serialisable: a
    slightly lossy cache entry beats a cache that quietly does nothing.
    """
    if hasattr(value, 'model_dump_json'):
        return value.model_dump_json()  # type: ignore[no-any-return]
    if isinstance(value, list) and value and hasattr(value[0], 'model_dump_json'):
        return json.dumps([item.model_dump(mode='json') for item in value])
    return json.dumps(value, default=str)


def _deserialize(raw: str) -> Any:
    """Inverse of :func:`_serialize` — pass through to ``json.loads``.

    Pydantic models are stored as plain dicts / lists and returned as such;
    callers that need a typed DTO must ``model_validate`` themselves.
    """
    return json.loads(raw)


async def cache_get_or_set(
    key: str,
    ttl: int,
    factory: Callable[[], Awaitable[Any]],
    *,
    deserializer: Callable[[str], Any] | None = None,
) -> Any:
    """Get value from cache, or compute and store it.

    Args:
        key: Cache key (e.g. 'org:123:modules').
        ttl: Time-to-live in seconds.
        factory: Async callable that computes the value on cache miss.
        deserializer: Optional callable that converts the cached JSON
            string back into a typed object (e.g.
            ``MyDTO.model_validate_json``). If omitted, returns the raw
            decoded value.

    Returns:
        Cached or freshly computed value.
    """
    if _redis is None:
        return await factory()

    try:
        cached = await _redis.get(key)
        if cached is not None:
            return deserializer(cached) if deserializer else _deserialize(cached)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — cache read must never break the endpoint
        logger.debug('Cache read failed for %s', key)

    value = await factory()

    try:
        await _redis.set(key, _serialize(value), ex=ttl)
    except Exception:  # noqa: BLE001 — cache write must never break the endpoint
        logger.debug('Cache write failed for %s', key)

    return value


async def cache_delete(*keys: str) -> None:
    """Delete one or more cache keys (for invalidation on write)."""
    if _redis is None:
        return
    try:
        await _redis.delete(*keys)
    except Exception:  # noqa: BLE001 — invalidation is best-effort
        logger.debug('Cache delete failed for %s', keys)


async def cache_delete_standalone(*keys: str) -> None:
    """Delete cache keys from a process that never ran the app lifespan.

    A CLI command writes to the database like any request does, but
    :func:`set_cache_redis` is only called at app startup, so there
    :func:`cache_delete` finds no client and silently does nothing -- and the
    running app keeps serving the old answer until the TTL. This opens a
    short-lived connection from ``REDIS_URL`` instead, and falls back to the
    injected client when there is one. Like :func:`cache_delete`, a failure is
    logged and swallowed: the write has already committed.
    """
    if _redis is not None:
        await cache_delete(*keys)
        return
    try:
        from redis.asyncio import Redis

        from app.config import settings

        client = Redis.from_url(settings.REDIS_URL)
        try:
            await client.delete(*keys)
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — invalidation is best-effort
        logger.debug('Standalone cache delete failed for %s', keys)


async def cache_invalidate_org_queries(org_id: UUID) -> None:
    """Invalidate every cached analytics query of *org_id*.

    One ``INCR`` on the organization's version key, so a write pays the same
    price whether the organization holds three cached answers or three
    thousand: the entries are not touched at all, and neither is the rest of
    the keyspace. The previous implementation walked it (``SCAN`` for
    ``org:{id}:query:*``, then a ``DELETE`` per key), which made every
    journal entry cost grow with the number of cached entries — and, because
    ``SCAN`` visits the whole database, with the keys everybody else had
    cached too. The next read simply resolves a key under the new version
    and recomputes; the stale entries are unreachable garbage that their own
    TTL deletes.

    Returns nothing: no caller used the count, and the honest count is no
    longer knowable without the walk this exists to avoid.
    """
    if _redis is None:
        return
    try:
        await _redis.incr(org_query_version_key(org_id))
    except Exception:  # noqa: BLE001 — invalidation must never break writes
        logger.debug('Cache invalidate failed for org %s', org_id)
