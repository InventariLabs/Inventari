"""Profile switch service — dry-run and apply paths.

The dry-run path is a thin wrapper around the pure planner from
:mod:`app.services.profile_switch_planner`. It must:

* read the organization's current ``enabled_modules`` and
  ``active_profile_id``,
* compute the deterministic ``ProfileSwitchPlan``,
* return it without any DB writes, lifecycle hooks, seed, or cache
  invalidation.

The apply path executes the plan transactionally:

1. Build the plan.
2. Disable modules in reverse-topological order.
3. Apply the profile seed in insert-only mode (no overwrite).
4. Apply ``module_config`` presets through the shared path, which journals
   every namespace it moved.
5. Enable modules in topological order.
6. Persist the new ``enabled_modules``, ``active_profile_id``, and
   ``onboarding_completed`` on the organization.
7. Record the module events; the module cache is invalidated once the
   caller's transaction commits.

The steps run in a savepoint: if any fails, the switch is rolled back whole,
what the caller wrote before stays, and the ``org:{id}:modules`` cache key is
NOT invalidated.

"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.core.db_utils import after_commit
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.module_registry import module_registry
from app.core.module_safety import ALWAYS_ON_MODULES, is_always_on
from app.core.product_profiles import apply_profile_seed, get_profile
from app.services.module_lifecycle_service import (
    ModuleLifecycleError,
    disable_modules_async,
    enable_modules_async,
)
from app.services.profile_module_config_service import (
    apply_profile_module_config_async,
)
from app.services.profile_switch_planner import (
    ProfileSwitchPlan,
    build_profile_switch_plan,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core._base_module import BaseModule
    from app.core.contracts import UserContextDTO
    from app.core.product_profiles import ProductProfile
    from app.models.organization import Organization

logger = logging.getLogger(__name__)


class ProfileSwitchApplyError(RuntimeError):
    """Raised when a profile switch cannot be applied.

    The switch ran in a savepoint, rolled back when this is raised; what the
    caller wrote before asking still stands, and its fate is the caller's.
    """


def preview_profile_switch(
    *,
    organization: Organization,
    profile: ProductProfile,
    modules: Sequence[BaseModule] | None = None,
) -> ProfileSwitchPlan:
    """Compute the diff for a profile switch without applying it.

    Args:
        organization: The organization to switch.
        profile: The target ``ProductProfile``.
        modules: Optional explicit list of registered modules. If not
            provided, the live ``module_registry`` is used.

    Returns:
        A :class:`ProfileSwitchPlan` describing the would-be change.

    Raises:
        ProfileSwitchError: If the target is invalid (unknown module,
            dependency cycle, etc.).
    """
    if modules is None:
        modules = list(module_registry.get_all())

    source = (
        get_profile(organization.active_profile_id)
        if organization.active_profile_id
        else None
    )
    plan = build_profile_switch_plan(
        current_modules=organization.enabled_modules or [],
        profile=profile,
        modules=list(modules),
        always_on=frozenset(name for name in ALWAYS_ON_MODULES if is_always_on(name)),
        source_profile=source,
    )

    # Stamp the from_profile_id from the org (the planner does not read
    # the org — keeping it pure).
    return plan.model_copy(update={'from_profile_id': organization.active_profile_id})


async def apply_profile_switch(
    *,
    db: AsyncSession,
    organization: Organization,
    profile: ProductProfile,
    modules: Sequence[BaseModule] | None = None,
    user: UserContextDTO | None = None,
) -> ProfileSwitchPlan:
    """Apply a profile switch transactionally.

    The function:

    1. Builds the plan via the pure planner.
    2. Runs disable hooks in reverse-topological order.
    3. Applies the profile seed in insert-only mode (no overwrite of
       user customisations). The seeder does NOT commit; the caller
       owns the transaction.
    4. Applies ``module_config`` presets through the shared settings path,
       which names what it moved in the journal.
    5. Runs enable hooks in topological order.
    6. Persists ``enabled_modules``, ``active_profile_id``, and
       ``onboarding_completed`` on the organization.
    7. Records a module-enabled/disabled event per changed module in the
       outbox; the module caches are invalidated once the caller commits.

    The steps run in a savepoint: on any failure the switch is rolled back
    whole, the caller's earlier writes stay, and the cache is left untouched.

    Raises:
        ProfileSwitchApplyError: If the plan is invalid or any
            lifecycle hook, seed, or settings update fails.
    """
    if modules is None:
        modules = list(module_registry.get_all())

    from_profile_id = organization.active_profile_id

    source = get_profile(from_profile_id) if from_profile_id else None
    plan = build_profile_switch_plan(
        current_modules=organization.enabled_modules or [],
        profile=profile,
        modules=list(modules),
        always_on=frozenset(name for name in ALWAYS_ON_MODULES if is_always_on(name)),
        source_profile=source,
    )

    modules_by_name = {m.metadata.name: m for m in modules}

    disable_modules = [
        modules_by_name[name] for name in plan.disable_all if name in modules_by_name
    ]
    enable_modules = [
        modules_by_name[name] for name in plan.enable if name in modules_by_name
    ]

    try:
        async with db.begin_nested():
            # 1. Disable hooks in reverse-topological order.
            await disable_modules_async(
                disable_modules, organization.id, db=db, user=user
            )

            # 2. Seed in insert-only mode — no commit; transaction stays open.
            await db.run_sync(
                lambda s: apply_profile_seed(
                    profile,
                    s,
                    organization_id=organization.id,
                    insert_only=True,
                    commit=False,
                )
            )

            # 2.5 A profile pick is also the route to the reader's language for
            # rows seeded by profiles and modules the organization left behind —
            # the picker shows them whatever the active profile is, and the
            # per-profile seed above only ever localizes its own list. Still-
            # literal rows move; names the organization typed stay.
            from app.seed_profiles._storage_type_catalogue import (
                localize_seeded_storage_types,
            )

            await db.run_sync(
                lambda s: localize_seeded_storage_types(
                    s, organization_id=organization.id
                )
            )

            # 3. Apply module_config presets through the shared, journaling path.
            await apply_profile_module_config_async(
                db,
                organization,
                profile.module_config,
                default_modules=profile.default_modules,
                profile_id=profile.id,
                user_id=user.id if user is not None else None,
            )

            # 4. Enable hooks in topological order.
            await enable_modules_async(
                enable_modules, organization.id, db=db, user=user
            )

            # 5. Apply the document preset (value tracking etc.) when declared and
            # the warehouse module ends up enabled. Runs inside the transaction
            # (commit=False) so a failure rolls back the whole switch.
            await _apply_document_preset_async(
                db, organization, profile, plan.final_enabled_modules
            )

            # 6. Persist the new state on the organization.
            organization.enabled_modules = list(plan.final_enabled_modules)
            organization.active_profile_id = profile.id
            organization.onboarding_completed = True

            # 7. Record the module events in the same transaction.
            for name in plan.disable_all:
                await event_bus.emit_transactional(
                    db,
                    SystemEvent.MODULE_DISABLED,
                    TenantEventPayload.model_validate(
                        {'organization_id': str(organization.id), 'module_name': name}
                    ),
                )
            for name in plan.enable:
                await event_bus.emit_transactional(
                    db,
                    SystemEvent.MODULE_ENABLED,
                    TenantEventPayload.model_validate(
                        {'organization_id': str(organization.id), 'module_name': name}
                    ),
                )
            await db.flush()
    except ModuleLifecycleError as exc:
        raise ProfileSwitchApplyError(str(exc)) from exc
    except ProfileSwitchApplyError:
        raise
    except Exception as exc:  # rolled back and re-raised as the switch's own error
        logger.exception('Profile switch failed for %s', profile.id)
        raise ProfileSwitchApplyError(f'Profile switch failed: {exc}') from exc

    # 8. A profile switch rewrites the enabled set wholesale, and the
    # per-request module guard was caching the old one. Cleared once the
    # caller has committed: earlier, a concurrent read re-caches the old set
    # for the full TTL.
    from app.core._require_module import invalidate_org_module_caches

    org_id = organization.id
    after_commit(db, lambda: invalidate_org_module_caches(org_id))

    if plan.offer_location_renumbering:
        # The stickers on the shelves carry random codes, and they stay: the
        # switch only offers shelf codes, the warehouse renumbers on request.
        logger.info(
            'Organization %s now numbers locations like shelves; '
            'its existing codes were kept and renumbering is offered',
            organization.id,
        )

    return plan.model_copy(update={'from_profile_id': from_profile_id})


async def _apply_document_preset_async(
    db: AsyncSession,
    organization: Organization,
    profile: ProductProfile,
    final_enabled_modules: list[str],
) -> None:
    """Apply ``profile.document_preset`` inside the switch transaction.

    Mirrors :func:`app.services.onboarding_service._apply_document_preset_async`
    but does NOT commit — the caller owns the transaction so that a preset
    failure rolls back the entire switch atomically.
    """
    if not profile.document_preset:
        return
    if 'warehouse' not in final_enabled_modules:
        logger.warning(
            'Profile %s declares document_preset %r but documents is not '
            'enabled after the switch — skipping',
            profile.id,
            profile.document_preset,
        )
        return
    from app.modules.warehouse.document_profile_service import apply_preset

    try:
        await apply_preset(db, organization.id, profile.document_preset)
    except ValueError as exc:
        logger.warning(
            'Profile %s document_preset %r is unknown (%s) — skipping',
            profile.id,
            profile.document_preset,
            exc,
        )
