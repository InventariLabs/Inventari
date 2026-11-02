"""Who is calling: the module a unit of work belongs to.

The certified model (ADR-019) trusts a module by name, and several seams
used to take that name as a parameter anyone could pass: settings and
secrets keyed a namespace by it, the scheduler keyed its task registry by
it, the event registry keyed event ownership by it. A module copying a
``module_name`` from another one read that module's settings — including
``get_decrypted_async``, the plaintext of another team's secret — unhooked
another module's jobs, or emitted events under another module's namespace,
and nothing in the failure left a trace of who actually ran.

The identity travels in a :class:`~contextvars.ContextVar` set at the
boundaries where control enters a module:

* ``ModuleIdentityMiddleware`` — every HTTP request whose path mounts a
  module's router;
* the lifecycle hooks in ``_lifespan`` / ``module_registry`` /
  ``module_lifecycle_service`` — ``on_install``, ``on_startup``,
  ``on_enable`` and friends;
* :class:`TaskScheduler` — before a module's periodic handler runs;
* the event bus — before a subscribed handler runs.

Core code runs with no identity bound, and no identity means no refusal:
the core may speak for any module. A module may only speak for itself,
which is the check the seams named above now make.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

_current_module: ContextVar[str | None] = ContextVar('current_module', default=None)


def current_module() -> str | None:
    """The module the current unit of work belongs to, or ``None`` for core."""
    return _current_module.get()


def bind_module(module_name: str) -> Token[str | None]:
    """Bind *module_name* as the current module; returns a reset token."""
    return _current_module.set(module_name)


def reset_module(token: Token[str | None]) -> None:
    """Undo a :func:`bind_module` with the token it returned."""
    _current_module.reset(token)


@contextmanager
def module_scope(module_name: str) -> Iterator[None]:
    """Run the block as *module_name*, restoring the previous identity."""
    token = bind_module(module_name)
    try:
        yield
    finally:
        reset_module(token)


def foreign_module_refusal(module_name: str, *, api: str) -> str | None:
    """Why the current module may not name *module_name*, or ``None``.

    Core code (no identity) may name anyone — the core owns every
    namespace. A module may name itself. Three allowances keep reviewed
    in-tree code working:

    * a module the repository ships is reviewed code (ADR-019); documents
      reaching approvals' settings through the approvals API is normal
      composition, not a copied name;
    * a name no loaded module answers to is not another module's
      namespace — ``core`` settings are core's, read by core services
      that run inside a module's request too;
    * core services may read their own.

    What is refused is the case the boundary exists for: a module the
    repository does not ship naming a *loaded module's* namespace.
    """
    caller = current_module()
    if caller is None or caller == module_name:
        return None
    from app.core.module_safety import REPO_SHIPPED_MODULES

    if caller in REPO_SHIPPED_MODULES:
        return None
    from app.core.module_registry import module_registry
    from app.core.module_safety import VIRTUAL_TOGGLEABLE_MODULES

    known = {module.metadata.name for module in module_registry.get_all()}
    if module_name not in known and module_name not in VIRTUAL_TOGGLEABLE_MODULES:
        return None
    return (
        f'{api}: module {caller!r} named {module_name!r} — a module may '
        f'only speak for itself'
    )


def refuse_foreign_module(module_name: str, *, api: str) -> None:
    """Raise ``PermissionError`` when the current module names another's."""
    refusal = foreign_module_refusal(module_name, api=api)
    if refusal is not None:
        raise PermissionError(refusal)


def module_name_from_api_path(path: str) -> str | None:
    """The module name a request path mounts, in module-name shape.

    ``/api/v1/purchase-orders/42`` → ``purchase_orders``; core segments
    (``/api/v1/labels``) return a name too — the caller decides whether a
    module actually answers to it.
    """
    segments = [segment for segment in path.split('/') if segment]
    if len(segments) < 3 or segments[0] != 'api' or segments[1] != 'v1':
        return None
    return segments[2].replace('-', '_')


def _module_mounted_at(name: str) -> str | None:
    """The loaded module whose router the segment *name* mounts, if any."""
    from app.core.module_registry import module_registry

    if module_registry.get(name) is not None:
        return name
    return None


class ModuleIdentityMiddleware:
    """Bind an HTTP request to the module whose router serves it.

    The path decides, and the registry confirms the name is a module this
    installation actually loaded: a core route (``/api/v1/labels``) looks
    the same to a string split, but no module answers to the name, and the
    core speaks for everyone. The binding is undone with the response, so
    one request can never leave its identity behind for the next.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return
        segment = module_name_from_api_path(scope.get('path', ''))
        module_name = _module_mounted_at(segment) if segment is not None else None
        if module_name is None:
            await self.app(scope, receive, send)
            return
        token = bind_module(module_name)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_module(token)


def event_registration_refusal(
    event_name: str, *, known_modules: frozenset[str] | set[str]
) -> str | None:
    """Why the current module may not register *event_name*, or ``None``.

    A runtime payload registration is an ownership claim. The name's
    namespace is not always the registrant's own name — ``purchase_orders``
    owns ``receipt.created_from_po``, ``recipes`` owns ``recipe.created`` —
    so the claim is refused exactly when the namespace is another loaded
    module's name. A namespace matching no module is the registrar's to
    take. Core code (no identity) registers on behalf of everyone.
    """
    caller = current_module()
    if caller is None:
        return None
    namespace = event_name.partition('.')[0]
    if namespace == caller or namespace not in known_modules:
        return None
    return (
        f'event {event_name!r} sits in module {namespace!r} namespace, and '
        f'module {caller!r} may not claim it'
    )


def event_emission_refusal(
    event_name: str,
    *,
    core_owned: bool,
    runtime_owner: str | None,
    known_modules: frozenset[str] | set[str],
) -> str | None:
    """Why the current module may not emit *event_name*, or ``None``.

    Core events (the core contract table) are the system's shared
    vocabulary: any module may emit them. An event registered at runtime
    belongs to the module that registered it — the name's shape and the
    owner can differ (``recipes`` registers ``recipe.created``), which is
    exactly why the owner is recorded rather than derived from the
    prefix. An unregistered name whose namespace is another loaded
    module's name would announce that module's event under a trace that
    does not belong to it; any other unregistered name is allowed.
    """
    caller = current_module()
    if caller is None or core_owned:
        return None
    if runtime_owner is not None:
        if runtime_owner == caller:
            return None
        return (
            f'event {event_name!r} is registered by module '
            f'{runtime_owner!r}; module {caller!r} may not emit it'
        )
    namespace = event_name.partition('.')[0]
    if namespace == caller or namespace not in known_modules:
        return None
    return (
        f'event {event_name!r} sits in module {namespace!r} namespace, and '
        f'module {caller!r} may not emit it'
    )


__all__ = [
    'bind_module',
    'current_module',
    'event_emission_refusal',
    'event_registration_refusal',
    'foreign_module_refusal',
    'module_scope',
    'refuse_foreign_module',
    'reset_module',
]
