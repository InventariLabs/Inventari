"""Pure planner for switching an organization to a new product profile.

This is a deterministic, side-effect-free function that computes the
delta between the org's current enabled-modules and the target profile's
``default_modules``, including:

* direct enable / disable lists — disable is a **delta** against the
  source profile's ``default_modules``: only modules that the source
  profile turned on and the target does not need are removed. Modules
  the operator enabled manually are never touched,
* a true reverse-dependency cascade: a fixpoint over ``requires`` that
  disables enabled modules outside the target which (transitively)
  require a module being removed, with a per-module reason,
* deterministic topological ordering for enable and reverse-topological
  ordering for disable,
* a list of modules whose preset ``module_config`` will be applied,
* validation errors for unknown modules, premium/entitlement conflicts,
  dependency cycles, and impossible targets.

When the organization has no ``active_profile_id`` (legacy), the source
profile is ``None`` and the switch is purely additive.

No DB, no hooks, no I/O. The caller is responsible for translating the
plan into actual lifecycle execution while keeping transaction ownership.

"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import CodedRejectionError

if TYPE_CHECKING:
    from app.core._base_module import BaseModule
    from app.core.product_profiles import ProductProfile


class ProfileSwitchError(CodedRejectionError):
    """Raised when a profile switch cannot be planned.

    Attributes:
        code: machine-readable error code (e.g. ``"unknown_module"``).
        context: structured details useful for HTTP responses.
    """


class ProfileSwitchPlan(BaseModel):
    """Pure, deterministic plan for switching an org to a new profile.

    No DB-, no hook-bound logic. The caller is responsible for applying
    the plan in the correct order:

    * disable modules in ``disable_all`` order (reverse topological),
    * enable modules in ``enable`` order (topological),
    * apply ``module_config`` entries in ``module_config_overwrite``,
    * persist ``final_enabled_modules`` and ``active_profile_id``
      atomically.
    """

    model_config = ConfigDict(frozen=True)

    from_profile_id: str | None
    to_profile_id: str
    enable: list[str]
    disable: list[str]
    cascade_disable: list[str]
    disable_all: list[str]
    unchanged: list[str]
    manual_kept: list[str]
    final_enabled_modules: list[str]
    module_config_overwrite: list[str]
    warnings: list[str] = Field(default_factory=list)
    #: The organization leaves random location codes for shelf codes. Its
    #: stickers keep their codes; renumbering is offered, never done here.
    offer_location_renumbering: bool = False


def build_profile_switch_plan(
    *,
    current_modules: Collection[str],
    profile: ProductProfile,
    modules: Sequence[BaseModule],
    always_on: Collection[str],
    allowed_modules: Collection[str] | None = None,
    source_profile: ProductProfile | None = None,
) -> ProfileSwitchPlan:
    """Build a deterministic switch plan.

    Args:
        current_modules: Modules currently enabled for the organization.
        profile: Target ``ProductProfile``.
        modules: All registered ``BaseModule`` instances.
        always_on: Modules that cannot be disabled — the effective set,
            ``ALWAYS_ON_MODULES`` filtered through ``is_always_on``.
        allowed_modules: Optional allow-list for premium/entitled modules.
            When ``None``, the entitlement check is skipped.
        source_profile: The organization's current ``ProductProfile``, if
            any. The disable delta is computed against its
            ``default_modules`` — modules enabled manually are kept.
            When ``None`` (legacy org), the switch is purely additive.

    Raises:
        ProfileSwitchError: If the target is invalid (unknown module,
            premium not allowed, dependency cycle, missing required dep).
    """
    current_set = set(current_modules)
    always_on_set = set(always_on)
    registered = {m.metadata.name for m in modules}
    requires_map: dict[str, list[str]] = {
        m.metadata.name: list(m.metadata.requires) for m in modules
    }

    target_base = set(profile.default_modules)

    _validate_profile_modules(
        target=target_base,
        registered=registered,
        always_on=always_on_set,
        allowed_modules=allowed_modules,
    )

    target = _dependency_closure(target_base | always_on_set, requires_map)

    source_defaults = set(source_profile.default_modules) if source_profile else set()
    direct_disable, cascade, cascade_reasons = _compute_disable(
        current_set=current_set,
        target=target,
        always_on=always_on_set,
        source_defaults=source_defaults,
        requires_map=requires_map,
    )

    all_disable = direct_disable | cascade

    enable = target - current_set - always_on_set
    enable_ordered = _topological_order(enable, requires_map)

    direct_disable_ordered = _reverse_topological_order(direct_disable, requires_map)
    cascade_ordered = _reverse_topological_order(cascade, requires_map)
    disable_all_ordered = _reverse_topological_order(all_disable, requires_map)

    unchanged = current_set & target

    manual_kept = sorted(
        current_set - target - direct_disable - cascade - always_on_set
    )

    final_enabled = (current_set | enable | always_on_set) - all_disable

    overwrite = sorted(m for m in profile.module_config if m in final_enabled)

    warnings = [
        f'{m} will be disabled because it requires {cascade_reasons[m]}.'
        for m in cascade_ordered
    ]

    return ProfileSwitchPlan(
        from_profile_id=None,
        to_profile_id=profile.id,
        enable=enable_ordered,
        disable=direct_disable_ordered,
        cascade_disable=cascade_ordered,
        disable_all=disable_all_ordered,
        unchanged=sorted(unchanged),
        manual_kept=manual_kept,
        final_enabled_modules=sorted(final_enabled),
        module_config_overwrite=overwrite,
        warnings=warnings,
        offer_location_renumbering=(
            source_profile is not None
            and source_profile.location_codes == 'random'
            and profile.location_codes == 'tree'
        ),
    )


def _validate_profile_modules(
    *,
    target: set[str],
    registered: set[str],
    always_on: set[str],
    allowed_modules: Collection[str] | None,
) -> None:
    """Reject unknown modules and disallowed premium modules.

    Virtual toggleable modules (no ``BaseModule`` registration, e.g.
    ``partners``) are permitted — they are legitimate profile members that
    the apply path persists directly on ``Organization.enabled_modules``.
    """
    from app.core.module_safety import VIRTUAL_TOGGLEABLE_MODULES

    unknown = sorted(target - registered - always_on - VIRTUAL_TOGGLEABLE_MODULES)
    if unknown:
        raise ProfileSwitchError(
            'profile_switch_unknown_modules',
            code='unknown_module',
            unknown_modules=unknown,
        )

    if allowed_modules is not None:
        allowed_set = set(allowed_modules)
        not_allowed = sorted(target - allowed_set)
        if not_allowed:
            raise ProfileSwitchError(
                'profile_switch_modules_not_allowed',
                code='module_not_allowed',
                not_allowed_modules=not_allowed,
            )


def _dependency_closure(
    target: set[str], requires_map: dict[str, list[str]]
) -> set[str]:
    """Expand ``target`` with all required dependencies (transitively).

    Raises ``ProfileSwitchError`` with code ``dependency_cycle`` if a cycle
    is detected, or ``dependency_closure`` if a required module is not
    registered.
    """
    closure = set(target)
    stack: list[str] = list(target)
    visited: set[str] = set()
    on_stack: set[str] = set()

    while stack:
        name = stack.pop()
        if name in visited:
            continue
        if name in on_stack:
            raise ProfileSwitchError(
                'module_dependency_cycle',
                code='dependency_cycle',
                module=name,
            )
        on_stack.add(name)
        for dep in requires_map.get(name, []):
            if dep not in closure:
                if dep not in requires_map:
                    raise ProfileSwitchError(
                        'profile_switch_dependency_unregistered',
                        code='dependency_closure',
                        module=name,
                        missing_dependency=dep,
                    )
                closure.add(dep)
                stack.append(dep)
        visited.add(name)
        on_stack.discard(name)

    return closure


def _compute_disable(
    *,
    current_set: set[str],
    target: set[str],
    always_on: set[str],
    source_defaults: set[str],
    requires_map: dict[str, list[str]],
) -> tuple[set[str], set[str], dict[str, str]]:
    """Return (direct_disable, cascade_disable, cascade_reasons).

    * direct_disable — profile-owned modules dropped by the switch:
      (source_defaults - target) ∩ current - always_on. Modules the
      operator enabled manually are never in this set.
    * cascade_disable — fixpoint: enabled modules outside target whose
      ``requires`` (transitively) hits a module being removed.
      cascade_reasons maps each to the removed dependency that pulled
      it in (first found, for the warning message).
    """
    direct = ((source_defaults - target) & current_set) - always_on
    cascade: set[str] = set()
    reasons: dict[str, str] = {}
    removed = set(direct)
    while True:
        newly = {
            m
            for m in (current_set - always_on - target - removed)
            if any(dep in removed for dep in requires_map.get(m, []))
        }
        if not newly:
            break
        for m in sorted(newly):
            reasons[m] = next(dep for dep in requires_map.get(m, []) if dep in removed)
        cascade |= newly
        removed |= newly
    return direct, cascade, reasons


def _topological_order(
    modules: set[str], requires_map: dict[str, list[str]]
) -> list[str]:
    """Return ``modules`` sorted so dependencies come before dependents.

    Modules that are not in ``requires_map`` (e.g. raw profile entries
    with no metadata) are kept in deterministic alphabetical order.
    """
    in_degree: dict[str, int] = dict.fromkeys(modules, 0)
    related: dict[str, set[str]] = {m: set() for m in modules}

    for module in modules:
        for dep in requires_map.get(module, []):
            if dep in modules:
                related[module].add(dep)
                in_degree[module] += 1

    ready = sorted(m for m, deg in in_degree.items() if deg == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for other in modules:
            if node in related[other]:
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    ready.append(other)
                    ready.sort()
        ready.sort()

    if len(order) != len(modules):
        remaining = set(modules) - set(order)
        raise ProfileSwitchError(
            'module_dependency_cycle_among',
            code='dependency_cycle',
            modules=sorted(remaining),
        )

    return order


def _reverse_topological_order(
    modules: set[str], requires_map: dict[str, list[str]]
) -> list[str]:
    """Return ``modules`` sorted so dependents are disabled before deps.

    Computed by topological order over the same set, then reversed.
    """
    topological = _topological_order(modules, requires_map)
    return list(reversed(topological))
