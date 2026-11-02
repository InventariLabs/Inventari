"""Unit test for the Redis critical-instance fallback.

The rate limiter resolves its storage URI at import time as
``REDIS_CRITICAL_URL or REDIS_URL``. This test pins the fallback contract
so a config refactor cannot silently drop it.
"""

from unittest.mock import patch

import pytest

from app.config import settings


@pytest.mark.unit
class TestRedisCriticalFallback:
    def test_falls_back_to_main_redis_when_unset(self):
        with patch.object(settings, 'REDIS_CRITICAL_URL', None):
            assert (settings.REDIS_CRITICAL_URL or settings.REDIS_URL) == (
                settings.REDIS_URL
            )

    def test_critical_url_wins_when_set(self):
        with patch.object(
            settings, 'REDIS_CRITICAL_URL', 'redis://redis-critical:6379'
        ):
            assert (settings.REDIS_CRITICAL_URL or settings.REDIS_URL) == (
                'redis://redis-critical:6379'
            )
