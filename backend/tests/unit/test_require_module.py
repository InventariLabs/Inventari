"""Tests for require_module dependency.

Verifies:
1. ALWAYS_ON modules always pass (no DB hit).
2. Missing organization_id → 403 with localized message.
3. Module not enabled → 403 with localized message containing module name.
4. Cache invalidation helper deletes the right key.
"""

from __future__ import annotations

import pytest

from app.core._require_module import (
    invalidate_enabled_modules,
    require_module,
)
from app.core.module_safety import ALWAYS_ON_MODULES
from app.i18n.service import get_error_message


@pytest.mark.unit
class TestRequireModule:
    """require_module dependency behavior."""

    async def test_always_on_module_passes_without_db(self):
        """ALWAYS_ON modules return True without any DB query."""
        mod_name = next(iter(ALWAYS_ON_MODULES))
        dep_fn = require_module(mod_name)

        # Should return True even with no db/user — ALWAYS_ON bypasses everything
        class _FakeUser:
            organization_id = None

        result = await dep_fn(current_user=_FakeUser(), db=None)
        assert result is True

    async def test_no_organization_returns_403(self):
        """User without org → 403 with localized 'no_organization' message."""
        dep_fn = require_module('recipes')

        class _FakeUser:
            organization_id = None

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await dep_fn(current_user=_FakeUser(), db=None)

        assert exc_info.value.status_code == 403
        # Message should contain a localized string, not hardcoded English
        assert exc_info.value.detail  # non-empty

    async def test_module_not_enabled_returns_403_with_name(self):
        """Disabled module → 403 with module name in message."""

        class _FakeUser:
            organization_id = '00000000-0000-0000-0000-000000000001'

        class _FakeDb:
            async def scalar(self, *args, **kwargs):
                # The enabled set, which is what the guard reads and caches.
                return ['core', 'items']

        # Bypass cache — force DB query
        import app.core.cache as cache_mod

        original_redis = cache_mod._redis
        cache_mod._redis = None

        try:
            from fastapi import HTTPException

            dep_fn = require_module('recipes')
            with pytest.raises(HTTPException) as exc_info:
                await dep_fn(current_user=_FakeUser(), db=_FakeDb())

            assert exc_info.value.status_code == 403
            assert exc_info.value.detail['code'] == 'MODULES_NOT_ENABLED'
            assert 'recipes' in exc_info.value.detail['message']
        finally:
            cache_mod._redis = original_redis


@pytest.mark.unit
class TestI18nKeys:
    """The module error keys exist in all languages."""

    @pytest.mark.parametrize('lang', ['en', 'pl'])
    def test_no_organization_key_exists(self, lang):
        msg = get_error_message('modules_no_organization', lang)
        assert msg != 'modules_no_organization', f'Key missing for {lang}'

    @pytest.mark.parametrize('lang', ['en', 'pl'])
    def test_not_enabled_key_formats_module_name(self, lang):
        msg = get_error_message('modules_not_enabled', lang, module_name='test_mod')
        assert 'test_mod' in msg
        assert msg != 'modules_not_enabled'


@pytest.mark.unit
class TestCacheInvalidation:
    """One key per organization, so one call forgets the whole set."""

    async def test_invalidate_calls_cache_delete(self):
        import unittest.mock as mock

        with mock.patch('app.core._require_module.cache_delete') as mock_delete:
            await invalidate_enabled_modules('org-123')
            mock_delete.assert_called_once_with('org:org-123:modules:enabled')
