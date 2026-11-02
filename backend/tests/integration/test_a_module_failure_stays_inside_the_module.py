"""A module's interceptor speaks only for organizations that have that module.

Interceptors are registered once, globally, during startup — every
organization shares one pipeline.  That is fine while nothing fails: an
interceptor belonging to a module the organization never enabled still ran,
and a plain ``RuntimeError`` raised from a ``before_*`` hook aborted the whole
write.  A module nobody asked for could therefore take down item creation,
and the only trace said which class raised — not which module it came from.

The pipeline now asks the same question the HTTP gate asks
(``Organization.is_module_enabled_value`` against the organization's enabled
set) and skips interceptors whose module is off.  Interceptors that do run
still fail loudly, but the log names their module.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core._require_module import invalidate_enabled_modules
from app.core.context import ModuleContext, build_module_context
from app.core.interceptors import (
    InterceptorError,
    ItemInterceptor,
    interceptor_pipeline,
)
from app.models.organization import Organization
from app.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: The module one of the test interceptors claims to come from.  It is not
#: registered anywhere, so no organization ever gets it by default.
_DISABLED_MODULE = 'notenabled'

#: A non-empty enabled set, which is also the interesting case for
#: ``is_module_enabled_value``: with a list in hand the answer is membership,
#: not the registered-not-premium default.
_ENABLED_WITHOUT_IT = ['core', 'items', 'locations', 'categories']

#: What ``type(interceptor).__module__`` reads for an in-tree interceptor.
_MODULE_PATH = f'app.modules.{_DISABLED_MODULE}.interceptors'


class _ExplodingInterceptor(ItemInterceptor):
    """A ``before_create`` hook that raises a plain ``RuntimeError``."""

    __module__ = _MODULE_PATH

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        raise RuntimeError('the module blew up')

    async def before_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return changes


class _BlockingInterceptor(ItemInterceptor):
    """A ``before_create`` hook that refuses the way interceptors are meant to."""

    __module__ = _MODULE_PATH

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        raise InterceptorError('blocked by an enabled module')

    async def before_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return changes


async def _context(
    db: AsyncSession,
    org: Organization,
    user: User,
    modules: list[str],
) -> ModuleContext:
    """Give *org* exactly these modules and build the request context."""
    org.enabled_modules = list(modules)
    await db.flush()
    await invalidate_enabled_modules(org.id)
    return build_module_context(db, org.id, user)


def _data() -> dict[str, Any]:
    return {'name': 'Shelf A'}


class TestAModuleFailureStaysInsideTheModule:
    async def test_disabled_module_interceptor_is_skipped(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        context = await _context(
            db, async_test_household, async_test_user, _ENABLED_WITHOUT_IT
        )
        interceptor = _ExplodingInterceptor()
        interceptor_pipeline.register_item_interceptor(interceptor)
        try:
            result = await interceptor_pipeline.run_before_item_create(_data(), context)
        finally:
            interceptor_pipeline.unregister_item_interceptor(interceptor)

        assert result == _data()
        # The answer is remembered on the context, so the next hook in the
        # same request does not ask the database again.
        assert isinstance(context.enabled_modules, frozenset)

    async def test_enabled_module_interceptor_still_fails_loudly(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        db = real_async_db_session
        context = await _context(
            db,
            async_test_household,
            async_test_user,
            [*_ENABLED_WITHOUT_IT, _DISABLED_MODULE],
        )
        interceptor = _ExplodingInterceptor()
        interceptor_pipeline.register_item_interceptor(interceptor)
        try:
            with (
                caplog.at_level(logging.ERROR, logger='app.core._interceptor_pipeline'),
                pytest.raises(RuntimeError, match='blew up'),
            ):
                await interceptor_pipeline.run_before_item_create(_data(), context)
        finally:
            interceptor_pipeline.unregister_item_interceptor(interceptor)

        assert _DISABLED_MODULE in caplog.text

    async def test_enabled_module_interceptor_error_still_propagates(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        context = await _context(
            db,
            async_test_household,
            async_test_user,
            [*_ENABLED_WITHOUT_IT, _DISABLED_MODULE],
        )
        interceptor = _BlockingInterceptor()
        interceptor_pipeline.register_item_interceptor(interceptor)
        try:
            with pytest.raises(InterceptorError) as exc_info:
                await interceptor_pipeline.run_before_item_create(_data(), context)
        finally:
            interceptor_pipeline.unregister_item_interceptor(interceptor)

        assert exc_info.value.error_code == 'INTERCEPTOR_BLOCKED'
