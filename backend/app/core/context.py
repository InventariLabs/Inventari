from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core._event_bus import EventBus, handler_name
from app.core.async_utils import maybe_await
from app.core.contracts import UserContextDTO
from app.core.events import EventPayload, SystemEvent, TenantEventPayload
from app.core.scoped_session import AsyncModuleScopedSession


def build_module_context(
    db: Any,
    organization_id: UUID | str | None,
    user: Any = None,
) -> ModuleContext:
    """Build a ModuleContext with the standard event-bus wiring.

    Normalises ``organization_id`` to ``str`` (or None when absent —
    the old inline ``str(user.organization_id)`` produced the literal
    ``"None"`` for org-less callers).
    """
    from app.core.events import event_bus

    return ModuleContext(
        event_bus=event_bus,
        organization_id=str(organization_id) if organization_id is not None else None,
        user=user,
        db=db,
    )


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ModuleContext:
    """
    What a module is handed to interact with the core system.

    Tenant scoping lives in the event bus (``ctx.emit`` / ``ctx.subscribe``)
    and in ``ctx.organization_id``. ``ctx.db`` is the request's raw ``Session``
    and is not scoped to the organization — what keeps a module to its own
    tenant is review and certification, not a boundary this object draws
    (ADR-019).

    Provides:
    - ``ctx.db`` – the underlying ``Session`` (raw, not scoped).
    - ``ctx.emit / ctx.subscribe`` – tenant-scoped event bus access.
    """

    def __init__(
        self,
        event_bus: EventBus,
        organization_id: str | None = None,
        user: UserContextDTO | None = None,
        db: Any = None,
        enabled_modules: frozenset[str] | None = None,
    ) -> None:
        self.organization_id = organization_id
        self._event_bus = event_bus
        self.user = user
        self._db = db
        #: Filled in by the interceptor pipeline on first use, then shared by
        #: every hook dispatched through this context, so one request asks the
        #: database once rather than once per interceptor.
        self.enabled_modules = enabled_modules

    # ------------------------------------------------------------------
    # Async session factories (outside request lifecycle)
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def tenant_session(
        self, organization_id: str | UUID
    ) -> AsyncIterator[AsyncModuleScopedSession]:
        """Per-tenant DB session with an explicit organization_id.

        Use this in global modules that handle events for multiple
        organizations and need to create a scoped session for a specific
        tenant from the event payload.

        Usage::

            async with ctx.tenant_session(payload.organization_id) as db:
                await my_tenant_read(db)
        """
        from app.database import AsyncSessionLocal

        org_uuid = (
            UUID(organization_id)
            if isinstance(organization_id, str)
            else organization_id
        )
        async with AsyncSessionLocal() as raw:  # type: ignore[misc]
            yield AsyncModuleScopedSession(raw, org_uuid)

    @asynccontextmanager
    async def global_session(self) -> AsyncIterator[AsyncSession]:
        """Unscoped session for GLOBAL startup seeders (no tenant context).

        Use ONLY for system-wide reference data (unit conversions,
        ingredient defaults, etc.), never for tenant data.

        Usage::

            async with ctx.global_session() as db:
                await seed_system_conversions(db)
        """
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as raw:  # type: ignore[misc]
            yield raw

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_name: SystemEvent | str,
        handler: Callable[[EventPayload], Any],
    ) -> None:
        """Register a handler tightly scoped to this module's tenant context."""

        async def wrapper(payload: EventPayload) -> None:
            await maybe_await(handler, payload)

        # Tenant scoping is enforced by the bus at dispatch time. The name is
        # the module's function, not this closure: the delivery log keeps it.
        self._event_bus.subscribe(
            event_name,
            wrapper,
            org_filter=self.organization_id,
            name=handler_name(handler),
        )

    async def migrate_settings(
        self, module_name: str, migrate: Callable[..., Any]
    ) -> int:
        """Rewrite every organization's settings blob for *module_name*.

        The per-organization pass for a settings shape change, meant to be
        called from ``on_upgrade_async``: the hook runs once per
        installation, while the data it needs to rewrite is saved once per
        organization. Each blob older than the schema's declared ``version``
        is offered to ``migrate(organization_id, from_version, settings)``
        — see :meth:`CoreSettingsAPI.migrate_settings_async` for the
        callback's contract.

        Requires a database session on the context: the upgrade context
        built at boot carries the boot session.
        """
        from app.core.exceptions import ContractViolationError
        from app.core.public_api import core_api

        if self._db is None:
            raise ContractViolationError(
                'migrate_settings needs a database session: build the '
                'ModuleContext with db=... (the upgrade context does).'
            )
        return await core_api.settings.migrate_settings_async(
            self._db, module_name, migrate
        )

    async def emit(
        self, event_name: SystemEvent | str, payload: dict[str, Any]
    ) -> None:
        """Emit an event, automatically scoping to the current organization if applicable.

        Accepts ``SystemEvent`` enum values or plain strings.  Modules should
        use the convention ``"<module>.<event_name>"`` for custom events
        (e.g. ``"rental.reservation_created"``).
        """
        if self.organization_id:
            tenant_payload = TenantEventPayload(
                organization_id=self.organization_id, **payload
            )
            await self._event_bus.emit(event_name, tenant_payload)
        else:
            await self._event_bus.emit(event_name, EventPayload(**payload))
