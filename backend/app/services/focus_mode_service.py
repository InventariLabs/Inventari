"""Single-module focus mode — enter, leave, and preview.

An organization can focus on one module: the workspace narrows to that module
and what it needs, and everything else steps back. The mode is carried by two
columns on the organization — ``focus_module`` (the choice, or NULL outside the
mode) and ``pre_focus_enabled_modules`` (the enabled set captured on entry).

The heavy lifting reuses the profile-switch planner rather than growing a
parallel machine: focusing on a module is planned exactly like switching to a
profile whose ``default_modules`` is the focus choice and its declared
background providers. The planner's dependency
closure adds what the module requires, its reverse cascade and per-module
reasons say what switches off and why, and its validation rejects a target the
organization has no right to. What is different from a profile switch:

* nothing is seeded and no module settings are overwritten — focus changes
  which modules are on, not what they contain,
* leaving restores the snapshot taken on entry — the state before the choice,
  not the active profile's defaults — plus the focus module and what it needs,
  and ``active_profile_id`` is never touched, so the profile survives the mode
  unchanged. The focus module stays on because it is the one the organization
  chose: entered at onboarding the snapshot predates it, and restoring that
  alone would switch it off.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import after_commit
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import CodedRejectionError
from app.core.module_registry import module_registry
from app.core.module_safety import (
    ALWAYS_ON_MODULES,
    VIRTUAL_TOGGLEABLE_MODULES,
    is_always_on,
)
from app.core.product_profiles import ProductProfile, get_profile
from app.models.organization import Organization
from app.services.audit_service import log_action_async
from app.services.module_lifecycle_service import (
    ModuleLifecycleError,
    disable_modules_async,
    enable_modules_async,
)
from app.services.profile_switch_planner import (
    ProfileSwitchPlan,
    build_profile_switch_plan,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import UserContextDTO

logger = logging.getLogger(__name__)


async def load_org_for_focus_async(
    db: AsyncSession, organization_id
) -> Organization | None:
    """The organization row with the deferred focus columns eager-loaded.

    ``focus_module``, ``pre_focus_enabled_modules`` and ``active_profile_id``
    are deferred on the model; reading any of them after the load would fire a
    lazy SELECT outside the greenlet, so the query undeferred them up front.
    The API layer hands the id down rather than touching the model itself.
    """
    return (
        await db.execute(
            select(Organization)
            .options(
                undefer(Organization.focus_module),
                undefer(Organization.pre_focus_enabled_modules),
                undefer(Organization.active_profile_id),
            )
            .where(Organization.id == organization_id)
        )
    ).scalar_one_or_none()


class FocusModeError(CodedRejectionError):
    """Raised when focus mode cannot be entered or left.

    Attributes:
        code: machine-readable error code (e.g. ``"focus_module_not_allowed"``).
        context: structured details useful for HTTP responses.
    """


class FocusModeApplyError(RuntimeError):
    """Raised when entering or leaving focus mode fails mid-apply.

    The apply ran in a savepoint, rolled back when this is raised; what the
    caller wrote before asking still stands, and its fate is the caller's.
    """


def _focus_profile(focus_module: str) -> ProductProfile:
    """A synthetic profile containing the focus choice and background providers.

    Feeding this to the planner is what computes ``[focus] + background + requires`` as the
    target set — the same dependency closure a profile switch uses. The seed
    name is empty on purpose: focus mode never seeds.
    """
    module = module_registry.get(focus_module)
    background = module.focus_background_modules if module else ()
    return ProductProfile(
        id=f'focus:{focus_module}',
        name=f'Focus: {focus_module}',
        description='Single-module focus mode',
        default_modules=[focus_module, *background],
        seed_profile='',
    )


def _build_focus_plan(
    organization: Organization,
    focus_module: str,
    current_modules: list[str] | None = None,
) -> ProfileSwitchPlan:
    """Plan the enabled-set delta for focusing on *focus_module* (pure).

    *current_modules* defaults to the organization's enabled set.
    """
    source = (
        get_profile(organization.active_profile_id)
        if organization.active_profile_id
        else None
    )
    return build_profile_switch_plan(
        current_modules=(
            organization.enabled_modules or []
            if current_modules is None
            else current_modules
        ),
        profile=_focus_profile(focus_module),
        modules=list(module_registry.get_all()),
        always_on=frozenset(name for name in ALWAYS_ON_MODULES if is_always_on(name)),
        source_profile=source,
    )


def _validate_focus_target(organization: Organization, focus_module: str) -> None:
    """Reject a focus choice the organization cannot stand behind.

    The always-on floor is not a focus candidate, an unknown module is not a
    module, and a premium module the organization has not unlocked is not
    theirs to focus on. Each refusal carries a machine-readable code so the
    endpoint can say why in the reader's language.
    """
    if is_always_on(focus_module):
        raise FocusModeError(
            'focus_mode_module_always_on',
            code='focus_module_always_on',
            module=focus_module,
        )

    module_instance = module_registry.get(focus_module)
    if module_instance is None and focus_module not in VIRTUAL_TOGGLEABLE_MODULES:
        raise FocusModeError(
            'focus_mode_module_unregistered',
            code='unknown_module',
            module=focus_module,
        )

    if (
        module_instance is not None
        and module_instance.metadata.is_premium
        and focus_module not in (organization.allowed_modules or [])
    ):
        raise FocusModeError(
            'focus_mode_module_not_enabled',
            code='focus_module_not_allowed',
            module=focus_module,
        )


def preview_focus_mode(
    *, organization: Organization, focus_module: str
) -> ProfileSwitchPlan:
    """Compute what focusing on *focus_module* would change, without applying.

    Raises:
        FocusModeError: If the choice is invalid (always-on, unknown, premium
            not unlocked).
        ProfileSwitchError: If the planner rejects the target (dependency
            cycle, missing dependency).
    """
    _validate_focus_target(organization, focus_module)
    return _build_focus_plan(organization, focus_module)


async def _apply_module_delta(
    db: AsyncSession,
    organization: Organization,
    *,
    to_disable: list[str],
    to_enable: list[str],
    user: UserContextDTO | None,
) -> None:
    """Run disable/enable lifecycle hooks for a computed module delta.

    Only registered backend modules have hooks; virtual and frontend-only
    names are persisted on ``enabled_modules`` but have nothing to run.
    """
    modules_by_name = {m.metadata.name: m for m in module_registry.get_all()}
    disable = [modules_by_name[n] for n in to_disable if n in modules_by_name]
    enable = [modules_by_name[n] for n in to_enable if n in modules_by_name]
    await disable_modules_async(disable, organization.id, db=db, user=user)
    await enable_modules_async(enable, organization.id, db=db, user=user)


async def _journal_module_switches(
    db: AsyncSession,
    organization: Organization,
    user: UserContextDTO,
    *,
    enabled: list[str],
    disabled: list[str],
) -> None:
    """One audit entry per module switched, in the shape of a store toggle."""
    for names, now in ((disabled, False), (enabled, True)):
        for name in names:
            await log_action_async(
                db,
                organization_id=organization.id,
                user_id=user.id,
                action=AuditAction.UPDATE,
                target_type=AuditTargetType.MODULE,
                target_id=organization.id,
                snapshot={
                    'name': name,
                    'before': {'enabled': not now},
                    'after': {'enabled': now},
                },
            )


async def _finalize_and_notify(
    db: AsyncSession,
    organization: Organization,
    *,
    disabled: list[str],
    enabled: list[str],
) -> None:
    """Record the module events; the cached module set goes once they commit."""
    for name in disabled:
        await event_bus.emit_transactional(
            db,
            SystemEvent.MODULE_DISABLED,
            TenantEventPayload.model_validate(
                {'organization_id': str(organization.id), 'module_name': name}
            ),
        )
    for name in enabled:
        await event_bus.emit_transactional(
            db,
            SystemEvent.MODULE_ENABLED,
            TenantEventPayload.model_validate(
                {'organization_id': str(organization.id), 'module_name': name}
            ),
        )
    await db.flush()

    # The per-request module guard caches the enabled set; the focus rewrite
    # must reach it, once the caller's transaction has committed — cleared
    # earlier, a concurrent read re-caches the old set for the full TTL.
    from app.core._require_module import invalidate_org_module_caches

    org_id = organization.id
    after_commit(db, lambda: invalidate_org_module_caches(org_id))


async def enter_focus_mode(
    *,
    db: AsyncSession,
    organization: Organization,
    focus_module: str,
    user: UserContextDTO | None = None,
) -> ProfileSwitchPlan:
    """Enter single-module mode on *focus_module*.

    Snapshots the current enabled set, plans and applies the narrowing through
    the profile-switch planner, and records the choice. Idempotency is a
    refusal: an organization already in focus mode must leave before focusing
    on something else, so the snapshot is never overwritten mid-mode.

    Raises:
        FocusModeError: If already in focus mode or the choice is invalid.
        ProfileSwitchError: If the planner rejects the target.
        FocusModeApplyError: If the apply fails (its savepoint rolled back).
    """
    if organization.focus_module:
        raise FocusModeError(
            'focus_mode_already_active',
            code='already_in_focus',
            module=organization.focus_module,
        )

    _validate_focus_target(organization, focus_module)
    plan = _build_focus_plan(organization, focus_module)

    snapshot = list(organization.enabled_modules or [])
    try:
        async with db.begin_nested():
            await _apply_module_delta(
                db,
                organization,
                to_disable=list(plan.disable_all),
                to_enable=list(plan.enable),
                user=user,
            )
            organization.enabled_modules = list(plan.final_enabled_modules)
            organization.focus_module = focus_module
            organization.pre_focus_enabled_modules = snapshot
    except ModuleLifecycleError as exc:
        raise FocusModeApplyError(str(exc)) from exc
    except Exception as exc:  # any apply failure rolls the mode back whole
        logger.exception('Entering focus mode failed for %s', focus_module)
        raise FocusModeApplyError(f'Entering focus mode failed: {exc}') from exc

    await _finalize_and_notify(
        db,
        organization,
        disabled=list(plan.disable_all),
        enabled=list(plan.enable),
    )
    return plan


async def exit_focus_mode(
    *,
    db: AsyncSession,
    organization: Organization,
    user: UserContextDTO | None = None,
) -> list[str]:
    """Leave single-module mode, restoring the state from before the choice.

    The enabled set goes back to the snapshot taken on entry — not to the
    active profile's defaults — with the focus module and what it needs kept
    on, and the focus columns are cleared. The ``active_profile_id`` was never
    touched, so the profile stands as it did. Each module the exit switches on
    or off is journalled, as a toggle in the store would be.

    Raises:
        FocusModeError: If the organization is not in focus mode.
        FocusModeApplyError: If the apply fails (its savepoint rolled back).
    """
    if not organization.focus_module:
        raise FocusModeError('focus_mode_not_active', code='not_in_focus')

    focus_module = organization.focus_module
    # Entered at onboarding, the snapshot predates the chosen module; entered
    # from Settings it already holds it. Either way the choice is kept.
    snapshot = list(organization.pre_focus_enabled_modules or [])
    chosen = _build_focus_plan(organization, focus_module, snapshot).enable
    snapshot += [m for m in chosen if m not in snapshot and not is_always_on(m)]
    current = list(organization.enabled_modules or [])
    to_enable = [m for m in snapshot if m not in current]
    to_disable = [m for m in current if m not in snapshot and not is_always_on(m)]

    try:
        async with db.begin_nested():
            await _apply_module_delta(
                db,
                organization,
                to_disable=to_disable,
                to_enable=to_enable,
                user=user,
            )
            organization.enabled_modules = snapshot
            organization.focus_module = None
            organization.pre_focus_enabled_modules = None
            if user is not None:
                await _journal_module_switches(
                    db, organization, user, enabled=to_enable, disabled=to_disable
                )
    except ModuleLifecycleError as exc:
        raise FocusModeApplyError(str(exc)) from exc
    except Exception as exc:  # any apply failure rolls the exit back whole
        logger.exception('Leaving focus mode failed')
        raise FocusModeApplyError(f'Leaving focus mode failed: {exc}') from exc

    await _finalize_and_notify(db, organization, disabled=to_disable, enabled=to_enable)
    return snapshot
