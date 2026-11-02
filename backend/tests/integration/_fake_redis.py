"""In-memory Redis fake for cache tests.

Implements the minimal subset of ``redis.asyncio.Redis`` used by
``app.core.cache``: ``get``, ``set`` (with ``ex`` TTL), ``delete``,
``incr``, ``scan_iter``, ``keys``.

Every call is also appended to :attr:`FakeRedis.commands`, so a test can say
what the cache layer *did* rather than only what it left behind — the
difference between an invalidation that walks the keyspace and one that
bumps a counter is invisible in the resulting data.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any


class FakeRedis:
    """Dict-backed stand-in for ``redis.asyncio.Redis``."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}
        self.commands: list[str] = []

    async def get(self, key: str) -> str | None:
        self.commands.append('get')
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at <= time.time():
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.commands.append('set')
        expires_at = time.time() + ex if ex else None
        self._store[key] = (value, expires_at)
        return True

    async def delete(self, *keys: str) -> int:
        self.commands.append('delete')
        deleted = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                deleted += 1
        return deleted

    async def incr(self, key: str) -> int:
        self.commands.append('incr')
        entry = self._store.get(key)
        value = int(entry[0]) + 1 if entry is not None else 1
        # Like the real INCR, the counter keeps whatever TTL it already had.
        self._store[key] = (str(value), entry[1] if entry is not None else None)
        return value

    async def scan_iter(self, match: str, count: int = 100) -> AsyncIterator[str]:
        import fnmatch

        self.commands.append('scan_iter')
        for key in list(self._store.keys()):
            if fnmatch.fnmatchcase(key, match):
                yield key

    async def keys(self, pattern: str = '*') -> list[str]:
        import fnmatch

        self.commands.append('keys')
        return [k for k in self._store if fnmatch.fnmatchcase(k, pattern)]

    def raw(self, key: str) -> Any:
        """Return the decoded stored value (for assertions)."""
        entry = self._store.get(key)
        if entry is None:
            return None
        return json.loads(entry[0])
