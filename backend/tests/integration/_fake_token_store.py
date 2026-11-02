"""In-memory stand-in for the Redis behind ``TokenBlacklist``.

The blacklist fails open without Redis in test mode, so a test that means to
exercise revocation has to give it a store — otherwise every assertion about
a revoked token passes for the wrong reason.

It lived as three byte-identical copies inside ``test_password_reset.py``,
which is why adding ``set`` to the blacklist broke them all at once. One copy
now, and one place to keep in step with the methods the blacklist calls:
``set`` (with ``ex`` and ``nx``), ``setex``, ``get``, ``exists``, ``delete``.

TTLs are recorded but not enforced: every window under test is far shorter
than any TTL the blacklist sets.
"""

from __future__ import annotations

from typing import Any


class FakeTokenStore:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self, key: str, value: Any, ex: int | None = None, nx: bool = False
    ) -> bool:
        """``nx`` keeps the value already stored — the real SET NX contract."""
        if nx and key in self.store:
            return False
        self.store[key] = str(value)
        return True

    async def setex(self, key: str, ttl: int, value: Any) -> None:
        self.store[key] = str(value)

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
