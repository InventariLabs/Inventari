"""Module-enforcement dependency with per-org caching and i18n messages.

Checks whether a module is enabled for the current user's organization.
Results are cached in Redis (short TTL) to avoid a per-request DB query.
The whole enabled set is cached under one key per organization, so every
place that writes that set invalidates it with a single call to
:func:`invalidate_enabled_modules` -- see its docstring for why there is one
key rather than one per module.

It replaces the uncached sync query + hardcoded English messages with a
cached async check + localized error messages.

Imports are deferred inside the closure because ``app.core.modules``
imports ``require_module`` at module load time — eagerly importing
``app.core.deps`` here would create a circular dependency.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_delete, cache_delete_standalone, cache_get_or_set

_CACHE_TTL = 60  # seconds — short TTL as stale-read fallback safety


def _enabled_modules_key(org_id: Any) -> str:
    return f'org:{org_id}:modules:enabled'


async def enabled_modules_for_org(db: AsyncSession, org_id: Any) -> frozenset[str]:
    """The modules *org_id* has enabled, read through the shared cache.

    One answer for everyone who asks "is this module on": the HTTP gate and
    the interceptor pipeline both start here, so a module that is off for an
    organization is off in both places.  Callers still resolve the answer with
    :meth:`Organization.is_module_enabled_value` — the raw set does not know
    about always-on modules or premium defaults.
    """

    async def _query() -> list[str]:
        from app.models.organization import Organization

        enabled = await db.scalar(
            select(Organization.enabled_modules).where(Organization.id == org_id)
        )
        return list(enabled) if enabled else []

    cached = await cache_get_or_set(
        _enabled_modules_key(org_id), ttl=_CACHE_TTL, factory=_query
    )
    return frozenset(cached or [])


async def _check_module_enabled(
    db: AsyncSession, org_id: Any, module_name: str
) -> bool:
    """Cache-aware check: is *module_name* enabled for *org_id*?"""
    from app.models.organization import Organization

    enabled = await enabled_modules_for_org(db, org_id)
    return Organization.is_module_enabled_value(list(enabled), module_name)


async def invalidate_enabled_modules(org_id: Any) -> None:
    """Forget what this organization had enabled.

    One key for the whole set rather than one per module, because the set
    is rewritten wholesale in three places -- the toggle, a profile switch
    and onboarding -- and only the first of them was invalidating anything.
    A per-module key made the other two a loop nobody wrote.
    """
    await cache_delete(_enabled_modules_key(org_id))


async def invalidate_org_module_caches(
    org_id: Any, *, standalone: bool = False
) -> None:
    """Forget both module caches of *org_id*: the list and the enabled set.

    Call it after the write has committed -- cleared earlier, a concurrent
    read re-caches the old committed set for the full TTL. A CLI command
    passes ``standalone=True``, because outside the app lifespan there is no
    cache client to delete through.
    """
    delete = cache_delete_standalone if standalone else cache_delete
    await delete(f'org:{org_id}:modules', _enabled_modules_key(org_id))


def require_module(module_name: str) -> Any:
    """FastAPI dependency that ensures *module_name* is enabled.

    Uses async ``get_async_db`` and a Redis-backed cache to avoid a
    per-request DB query. Error messages are localized.
    """

    # Import here to avoid circular import at module load time.
    from app.core.deps import get_async_db, get_current_user_context
    from app.core.module_safety import is_always_on

    async def _check_module(
        current_user: Any = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
    ) -> bool:
        from app.core.exceptions import catalogue_status_refusal

        if is_always_on(module_name):
            return True

        if not current_user.organization_id:
            raise catalogue_status_refusal(
                'modules_no_organization', status.HTTP_403_FORBIDDEN
            )

        enabled = await _check_module_enabled(
            db, current_user.organization_id, module_name
        )
        if not enabled:
            raise catalogue_status_refusal(
                'modules_not_enabled',
                status.HTTP_403_FORBIDDEN,
                module_name=module_name,
            )

        return True

    return _check_module
