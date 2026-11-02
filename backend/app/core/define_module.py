"""Declarative module registration — replaces boilerplate BaseModule subclassing.

Usage::

    # module.py — minimal (most modules)
    from app.core.define_module import define_module
    from .router import router

    module = define_module(router=router)

    # module.py — with options
    from datetime import timedelta
    from app.core.define_module import define_module, ModuleScheduledTask
    from .router import router

    def my_cleanup():
        ...

    module = define_module(
        router=router,
        interceptors=[MyInterceptor()],
        seed=seed_defaults,
        schedules=[ModuleScheduledTask('cleanup', timedelta(hours=1), my_cleanup)],
    )

Metadata is read from ``manifest.json`` (name, version, etc.) — single source of truth.
For modules that need full lifecycle control, subclassing ``BaseModule`` remains available.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.context import ModuleContext
from app.core.logging import get_logger
from app.core.module_manifest_schema import ModuleManifest

if TYPE_CHECKING:
    from fastapi import APIRouter

    from app.core.container import ServiceContainer

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModuleScheduledTask:
    """Scheduled task declarable via define_module(schedules=[...])."""

    name: str
    interval: timedelta
    handler: Callable[..., Any]
    is_persistent: bool = False


def _read_manifest(module_dir: Path) -> ModuleManifest:
    """Load manifest.json using the Pydantic schema."""
    return ModuleManifest.load(module_dir)


def _manifest_to_metadata(manifest: ModuleManifest) -> ModuleMetadata:
    return ModuleMetadata(
        name=manifest.name,
        version=manifest.version or '0.0.1',
        display_name=manifest.display_name or manifest.name.title(),
        description=manifest.description or '',
        icon=manifest.icon or 'box',
        module_type=manifest.module_type,
        category=manifest.category,
        is_reference=manifest.is_reference,
        requires=list(manifest.requires),
        optional_requires=list(manifest.optional_requires),
        capabilities=[str(capability) for capability in manifest.capabilities],
        author=manifest.author,
        license=manifest.license,
        homepage=manifest.homepage,
        requires_api_key=manifest.requires_api_key,
        # manifest.json is the single declaration point (see module docstring),
        # so define_module takes no `permissions` argument: a second source
        # would only be a second thing to keep in step.
        permissions=list(manifest.defined_permissions),
    )


@dataclass(frozen=True)
class _ModuleSpec:
    """Everything ``define_module`` was told, in one object.

    The declarative module used to be a class defined inside the factory, so
    every hook was a closure variable and ruff counted the whole nest as one
    28-branch function. The hooks travel in this spec instead.
    """

    metadata: ModuleMetadata
    router: APIRouter | None = None
    router_factory: Callable[[], APIRouter] | None = None
    interceptors: tuple[Any, ...] = ()
    schedules: tuple[ModuleScheduledTask, ...] = ()
    seed: Callable[[UUID, ModuleContext], None] | None = None
    register_services_hook: Callable[[ServiceContainer], None] | None = None
    register_contributions_hook: Callable[[], None] | None = None
    on_startup_hook: Callable[[ModuleContext], None] | None = None
    on_startup_async_hook: Callable[[ModuleContext], Awaitable[None]] | None = None
    on_install_hook: Callable[[ModuleContext], None] | None = None
    on_install_async_hook: Callable[[ModuleContext], Awaitable[None]] | None = None
    on_uninstall_hook: Callable[[ModuleContext], None] | None = None
    on_upgrade_hook: Callable[[str, ModuleContext], None] | None = None
    settings_schema: dict[str, Any] | None = None
    default_settings: dict[str, Any] | None = None


def _register_interceptors(interceptors: tuple[Any, ...]) -> None:
    """File each interceptor under the contribution slot matching its base class."""
    from app.core._interceptor_base import (
        CategoryInterceptor,
        ItemInterceptor,
        StorageInterceptor,
    )
    from app.core.contributions import contribution_registry

    slots = (
        (ItemInterceptor, 'item_interceptors'),
        (StorageInterceptor, 'storage_interceptors'),
        (CategoryInterceptor, 'category_interceptors'),
    )
    for interceptor in interceptors:
        for base, slot in slots:
            if isinstance(interceptor, base):
                contribution_registry.register(slot, interceptor)  # type: ignore[arg-type]
                break


def _register_schedules(
    schedules: tuple[ModuleScheduledTask, ...], module_name: str
) -> None:
    from app.core.scheduler import task_scheduler

    for task in schedules:
        task_scheduler.register(
            name=task.name,
            interval=task.interval,
            handler=task.handler,
            module_name=module_name,
            is_persistent=task.is_persistent,
        )


class _DeclarativeModule(BaseModule):
    """A ``BaseModule`` whose behaviour is the spec it was built from."""

    def __init__(self, spec: _ModuleSpec) -> None:
        self._spec = spec

    @property
    def metadata(self) -> ModuleMetadata:
        return self._spec.metadata

    def register_routes(self) -> Any:
        if self._spec.router is not None:
            return self._spec.router
        return self._spec.router_factory()  # type: ignore[misc]

    def on_enable(self, organization_id: UUID, context: ModuleContext) -> None:
        if self._spec.seed is not None:
            self._spec.seed(organization_id, context)

    def on_startup(self, context: ModuleContext) -> None:
        super().on_startup(context)
        if self._spec.schedules:
            _register_schedules(self._spec.schedules, self._spec.metadata.name)
        if self._spec.on_startup_hook is not None:
            self._spec.on_startup_hook(context)

    async def on_startup_async(self, context: ModuleContext) -> None:
        if self._spec.on_startup_async_hook is not None:
            await self._spec.on_startup_async_hook(context)

    def register_services(self, container: ServiceContainer) -> None:
        if self._spec.register_services_hook is not None:
            self._spec.register_services_hook(container)

    def register_contributions(self) -> None:
        _register_interceptors(self._spec.interceptors)
        if self._spec.register_contributions_hook is not None:
            self._spec.register_contributions_hook()

    def on_install(self, context: ModuleContext) -> None:
        super().on_install(context)
        if self._spec.on_install_hook is not None:
            self._spec.on_install_hook(context)

    async def on_install_async(self, context: ModuleContext) -> None:
        if self._spec.on_install_async_hook is not None:
            # Run migrations first, then the async hook (skip sync hook).
            self._run_module_migrations('upgrade')
            await self._spec.on_install_async_hook(context)
        else:
            self.on_install(context)

    def on_uninstall(self, context: ModuleContext) -> None:
        super().on_uninstall(context)
        if self._spec.on_uninstall_hook is not None:
            self._spec.on_uninstall_hook(context)

    def on_upgrade(self, old_version: str, context: ModuleContext) -> None:
        if self._spec.on_upgrade_hook is not None:
            self._spec.on_upgrade_hook(old_version, context)

    def get_settings_schema(self) -> dict[str, object] | None:
        return self._spec.settings_schema

    def get_default_settings(self) -> dict[str, object]:
        return dict(self._spec.default_settings or {})


def define_module(
    *,
    router: APIRouter | None = None,
    router_factory: Callable[[], APIRouter] | None = None,
    interceptors: list[Any] | None = None,
    seed: Callable[[UUID, ModuleContext], None] | None = None,
    schedules: list[ModuleScheduledTask] | None = None,
    register_services_hook: Callable[[ServiceContainer], None] | None = None,
    register_contributions_hook: Callable[[], None] | None = None,
    on_startup_hook: Callable[[ModuleContext], None] | None = None,
    on_startup_async_hook: Callable[[ModuleContext], Awaitable[None]] | None = None,
    on_install_hook: Callable[[ModuleContext], None] | None = None,
    on_install_async_hook: Callable[[ModuleContext], Awaitable[None]] | None = None,
    on_uninstall_hook: Callable[[ModuleContext], None] | None = None,
    on_upgrade_hook: Callable[[str, ModuleContext], None] | None = None,
    consumes_stock_quant: bool = False,
    settings_schema: dict[str, Any] | None = None,
    default_settings: dict[str, Any] | None = None,
) -> BaseModule:
    """Create a ``BaseModule`` instance declaratively.

    Parameters
    ----------
    router:
        The FastAPI router with module endpoints. Provide this **or** ``router_factory``.
    router_factory:
        Lazy alternative to ``router`` — called once during route registration.
        Use this when the router has circular import dependencies that prevent
        eager loading at module level.
    interceptors:
        Optional list of interceptor instances to register.
    seed:
        Optional ``on_enable(org_id: UUID, context)`` callback for seeding defaults.
    schedules:
        Optional list of ``ModuleScheduledTask`` instances to register on startup.
    register_services_hook:
        Optional ``register_services(container)`` override.
    register_contributions_hook:
        Optional ``register_contributions()`` override.
    on_startup_hook:
        Optional ``on_startup(context)`` override — called *after* default wiring.
    on_startup_async_hook:
        Optional async ``on_startup_async(context)`` override.
    on_install_hook:
        Optional ``on_install(context)`` override — called when module is installed.
        Runs *after* the default migration step. If not set, only migrations run.
    on_install_async_hook:
        Optional async ``on_install_async(context)`` override. Takes priority over
        ``on_install_hook`` — when provided, only the async hook runs (plus default
        migrations). Use this when the hook needs async DB access.
    on_uninstall_hook:
        Optional ``on_uninstall(context)`` override — called when module is uninstalled.
        Runs *after* the default migration step.
    on_upgrade_hook:
        Optional ``on_upgrade(old_version, context)`` override — called on the
        first boot after the installed version changes. Schema changes belong
        in the module's migrations, which ``module upgrade`` runs; this hook is
        for what a migration cannot express, such as rewriting stored settings
        into a shape the new version reads. Declaratively defined modules had
        no way to state one at all, so every module in the tree inherited the
        base class's ``pass``.
    settings_schema:
        Optional JSON Schema for module-level settings (``get_settings_schema``).
        When provided, set ``has_settings_schema: true`` in ``manifest.json`` —
        the two are pinned together by tests/unit/test_manifest_settings_schema.py.
    default_settings:
        Optional ``get_default_settings()`` values applied when the org has not
        overridden them.
    """
    if router is None and router_factory is None:
        raise ValueError('Either router or router_factory must be provided')
    import inspect

    caller_frame = inspect.stack()[1]
    caller_path = Path(caller_frame.filename).resolve()
    module_dir = caller_path.parent

    manifest = _read_manifest(module_dir)
    metadata = _manifest_to_metadata(manifest)
    metadata = metadata.model_copy(
        update={'consumes_stock_quant': consumes_stock_quant}
    )

    return _DeclarativeModule(
        _ModuleSpec(
            metadata=metadata,
            router=router,
            router_factory=router_factory,
            interceptors=tuple(interceptors or ()),
            schedules=tuple(schedules or ()),
            seed=seed,
            register_services_hook=register_services_hook,
            register_contributions_hook=register_contributions_hook,
            on_startup_hook=on_startup_hook,
            on_startup_async_hook=on_startup_async_hook,
            on_install_hook=on_install_hook,
            on_install_async_hook=on_install_async_hook,
            on_uninstall_hook=on_uninstall_hook,
            on_upgrade_hook=on_upgrade_hook,
            settings_schema=settings_schema,
            default_settings=default_settings,
        )
    )
