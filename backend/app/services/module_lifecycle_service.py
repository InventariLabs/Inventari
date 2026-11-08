"""Async module lifecycle executor.

Runs enable/disable hooks for a batch of modules in the correct
dependency order. Shared between the existing onboarding flow and the
new profile switch service.

Design:

* The executor is **async-only** (per repo Sync/Async Rule).
* Transaction ownership stays at the caller's level — the executor
  never commits. It may flush (modules are free to write inside their
  hooks) but never ends a transaction.
* Event emission also stays at the caller — the executor does not
  touch ``event_bus``.
* Enable runs in the order of ``module_names`` (caller must pass
  topological order so dependencies are enabled before dependents).
* Disable runs in reverse order so dependents are disabled before
  dependencies.
* Both ``on_enable`` and ``on_disable`` may be sync OR async; the
  executor awaits them if they return a coroutine.
* Errors are surfaced as ``ModuleLifecycleError`` so the caller can
  trigger a rollback.

"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.core._base_module import BaseModule
from app.core.context import build_module_context
from app.core.module_identity import module_scope


async def grant_default_permissions(
    module: BaseModule, organization_id: UUID, db: Any
) -> None:
    """Give the module's declared permissions to the roles it names.

    A manifest permission with ``default_roles: ["manager"]`` lands on this
    organization's role called ``manager``, if it has one. Roles are never
    created here: inventing an org-wide role as a side effect of enabling a
    module would be a surprising grant of authority. Where no role matches, the
    permission stays unassigned and only admins (who bypass permission checks)
    can use the feature until someone grants it explicitly.

    Idempotent — enabling a module twice does not duplicate entries, and a
    permission an admin deliberately removed is re-added only if the module is
    enabled again.
    """
    wanted = [p for p in module.metadata.permissions if p.default_roles]
    if not wanted:
        return

    from sqlalchemy import select

    from app.models.role import Role

    names = {name for p in wanted for name in p.default_roles}
    result = await db.execute(
        select(Role).where(
            Role.organization_id == organization_id,
            Role.name.in_(names),
        )
    )
    roles = {role.name: role for role in result.scalars()}
    if not roles:
        return

    for perm in wanted:
        for role_name in perm.default_roles:
            role = roles.get(role_name)
            if role is None or perm.key in (role.permissions or []):
                continue
            # Reassign rather than append: JSONB columns are not mutation-tracked,
            # so an in-place append would never reach the database.
            role.permissions = [*(role.permissions or []), perm.key]

    await db.flush()


class ModuleLifecycleError(RuntimeError):
    """Raised when a module lifecycle hook fails.

    The caller should treat this as a hard failure and roll back any
    in-progress transaction.
    """

    def __init__(self, module_name: str, hook: str, cause: BaseException) -> None:
        super().__init__(f'{hook} failed for module {module_name!r}: {cause}')
        self.module_name = module_name
        self.hook = hook
        self.__cause__ = cause


async def enable_modules_async(
    modules: Sequence[BaseModule],
    organization_id: UUID,
    *,
    db: Any,
    user: Any | None = None,
) -> None:
    """Run enable hooks for ``modules`` in dependency order.

    Args:
        modules: Registered module instances. The caller is responsible
            for ordering them so dependencies appear before dependents.
        organization_id: Target organization ID.
        db: Active ``AsyncSession``. The executor does NOT commit.
        user: Optional ``UserContextDTO`` — passed to the module via
            ``ModuleContext``. Required for modules whose ``on_enable``
            accesses the user (e.g. Equipment).

    Every enable path comes through here — onboarding, a profile switch, the
    store's toggle and the demo seed — and each runs both hooks:
    ``system_on_enable`` seeds what the module declares, then the module's own
    ``on_enable``. Onboarding used to run only the first, so a module that
    seeds in ``on_enable`` left every onboarded organization without it.
    """
    for module in modules:
        # The hooks are the module's own code: run them under its identity so
        # their settings/secret/event calls can speak for it.
        with module_scope(module.metadata.name):
            await _enable_one_module(
                module,
                organization_id,
                db=db,
                user=user,
            )


async def _enable_one_module(
    module: BaseModule,
    organization_id: UUID,
    *,
    db: Any,
    user: Any | None,
) -> None:
    try:
        await module.system_on_enable(organization_id, db, user=user)
    except Exception as exc:  # module hook: any failure is a lifecycle error
        raise ModuleLifecycleError(
            module.metadata.name, 'system_on_enable', exc
        ) from exc

    await grant_default_permissions(module, organization_id, db)

    context = build_module_context(db, organization_id, user)
    try:
        result = module.on_enable(organization_id, context)
    except Exception as exc:  # module hook: any failure is a lifecycle error
        raise ModuleLifecycleError(module.metadata.name, 'on_enable', exc) from exc
    if asyncio.iscoroutine(result):
        try:
            await result
        except Exception as exc:  # module hook: any failure is a lifecycle error
            raise ModuleLifecycleError(module.metadata.name, 'on_enable', exc) from exc


async def disable_modules_async(
    modules: Sequence[BaseModule],
    organization_id: UUID,
    *,
    db: Any,
    user: Any | None = None,
) -> None:
    """Run disable hooks for ``modules`` in reverse dependency order.

    Args:
        modules: Registered module instances. The executor reverses
            the order so dependents are disabled before their
            dependencies.
        organization_id: Target organization ID.
        db: Active ``AsyncSession``. The executor does NOT commit.
        user: Optional ``UserContextDTO`` — passed to the module via
            ``ModuleContext``.
    """
    for module in reversed(list(modules)):
        with module_scope(module.metadata.name):
            await _disable_one_module(module, organization_id, db=db, user=user)


async def _disable_one_module(
    module: BaseModule,
    organization_id: UUID,
    *,
    db: Any,
    user: Any | None,
) -> None:
    try:
        await module.system_on_disable(organization_id, db)
    except Exception as exc:  # module hook: any failure is a lifecycle error
        raise ModuleLifecycleError(
            module.metadata.name, 'system_on_disable', exc
        ) from exc

    context = build_module_context(db, organization_id, user)
    try:
        result = module.on_disable(organization_id, context)
    except Exception as exc:  # module hook: any failure is a lifecycle error
        raise ModuleLifecycleError(module.metadata.name, 'on_disable', exc) from exc
    if asyncio.iscoroutine(result):
        try:
            await result
        except Exception as exc:  # module hook: any failure is a lifecycle error
            raise ModuleLifecycleError(module.metadata.name, 'on_disable', exc) from exc
