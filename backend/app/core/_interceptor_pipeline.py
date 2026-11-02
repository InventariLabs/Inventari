from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from app.core._interceptor_base import (
    CategoryInterceptor,
    InterceptorError,
    ItemInterceptor,
    StorageInterceptor,
)
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.context import ModuleContext

logger = get_logger(__name__)

# Entity kind → attribute holding that kind's interceptor list.
_INTERCEPTOR_LISTS = {
    'item': '_item_interceptors',
    'storage': '_storage_interceptors',
    'category': '_category_interceptors',
}


def _module_of(interceptor: Any) -> str | None:
    """The module *interceptor* belongs to, or ``None`` when it is not a module's.

    An in-tree interceptor lives in ``app.modules.<name>.interceptors``, and
    ``type(...).__module__`` keeps saying so wherever it is imported from.  A
    double that merely behaves like one names its own file, so the pipeline
    has no module to ask about and never gates it.
    """
    parts = type(interceptor).__module__.split('.')
    if len(parts) >= 3 and parts[0] == 'app' and parts[1] == 'modules':
        return parts[2]
    return None


async def _enabled_modules(context: ModuleContext) -> frozenset[str] | None:
    """The enabled-module set to gate against, or ``None`` when unknowable.

    ``None`` means "do not gate": a context without a real organization or
    without a session — unit-test doubles, startup-time callers — keeps every
    registered interceptor running, exactly as before the gate existed.  The
    answer is written back onto the context, so the next hook of the same
    request reuses it instead of asking the database again.
    """
    cached = getattr(context, 'enabled_modules', None)
    if isinstance(cached, frozenset):
        return cached

    org_id = getattr(context, 'organization_id', None)
    db = getattr(context, '_db', None)
    if not isinstance(org_id, (str, UUID)) or db is None:
        return None

    from app.core._require_module import enabled_modules_for_org

    enabled = await enabled_modules_for_org(db, org_id)
    context.enabled_modules = enabled
    return enabled


async def _runs_for(interceptor: Any, context: ModuleContext) -> bool:
    """Is *interceptor*'s module enabled for the organization of this request?

    The identical question the HTTP gate asks, resolved by the identical
    definition of "enabled" (``Organization.is_module_enabled_value``) — two
    definitions of that word is the bug this whole gate exists to avoid.
    """
    module = _module_of(interceptor)
    if module is None:
        return True
    enabled = await _enabled_modules(context)
    if enabled is None:
        return True

    from app.models.organization import Organization

    return Organization.is_module_enabled_value(list(enabled), module)


@dataclass
class InterceptorPipeline:
    """Executes registered interceptors in priority order.

    This is the global pipeline singleton. Modules register their interceptors
    here during ``on_startup`` / ``register_contributions``.

    The 22 public ``run_*`` hooks are one-line delegations to three
    shared dispatch primitives instead of 22 duplicated bodies.
    """

    _item_interceptors: list[ItemInterceptor] = field(default_factory=list)
    _storage_interceptors: list[StorageInterceptor] = field(default_factory=list)
    _category_interceptors: list[CategoryInterceptor] = field(default_factory=list)

    def register_item_interceptor(self, interceptor: ItemInterceptor) -> None:
        """Register an item interceptor. Re-sorts by priority after each registration."""
        self._register(self._item_interceptors, interceptor)

    def register_storage_interceptor(self, interceptor: StorageInterceptor) -> None:
        """Register a storage interceptor. Re-sorts by priority after each registration."""
        self._register(self._storage_interceptors, interceptor)

    def register_category_interceptor(self, interceptor: CategoryInterceptor) -> None:
        """Register a category interceptor. Re-sorts by priority after each registration."""
        self._register(self._category_interceptors, interceptor)

    def unregister_item_interceptor(self, interceptor: ItemInterceptor) -> None:
        """Remove a previously registered item interceptor; a no-op if absent.

        Registration is a public operation, so undoing it is one too. Tests that
        register a blocker for the duration of one case were reaching into
        ``_item_interceptors`` to take it back out, which ties them to the
        pipeline's internals for the sake of a teardown.
        """
        if interceptor in self._item_interceptors:
            self._item_interceptors.remove(interceptor)

    @staticmethod
    def _register(interceptors: list[Any], interceptor: Any) -> None:
        if interceptor in interceptors:
            return
        interceptors.append(interceptor)
        interceptors.sort(key=lambda i: i.priority)
        logger.debug(
            'Registered interceptor %s (priority=%d)',
            type(interceptor).__name__,
            interceptor.priority,
        )

    # ------------------------------------------------------------------
    # Shared dispatch primitives
    # ------------------------------------------------------------------

    def _list_for(self, kind: str) -> list[Any]:
        return cast(list[Any], getattr(self, _INTERCEPTOR_LISTS[kind]))

    async def _create(
        self, kind: str, method: str, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Thread *data* through each interceptor's *method*; propagate errors."""
        for interceptor in self._list_for(kind):
            if not await _runs_for(interceptor, context):
                continue
            try:
                data = await getattr(interceptor, method)(data, context)
            except InterceptorError:
                raise
            except Exception:  # logged with the interceptor's name, then re-raised
                self._log_unexpected(interceptor, method)
                raise
        return data

    async def _update(
        self,
        kind: str,
        method: str,
        entity_id: UUID,
        changes: dict[str, Any],
        context: ModuleContext,
    ) -> dict[str, Any]:
        """Thread *changes* through each interceptor's *method*; propagate errors."""
        for interceptor in self._list_for(kind):
            if not await _runs_for(interceptor, context):
                continue
            try:
                changes = await getattr(interceptor, method)(
                    entity_id, changes, context
                )
            except InterceptorError:
                raise
            except Exception:  # logged with the interceptor's name, then re-raised
                self._log_unexpected(interceptor, method, entity_id)
                raise
        return changes

    async def _void(
        self,
        kind: str,
        method: str,
        context: ModuleContext,
        *args: Any,
        safe: bool = False,
    ) -> None:
        """Call *method* on every interceptor; missing hooks are skipped.

        With ``safe=True`` exceptions are logged and swallowed so a failing
        interceptor never breaks the main flow; otherwise they propagate.
        The first positional arg is the entity id, used in the error log.

        ``context`` is named in the signature rather than read off the tail of
        ``args``: the module gate needs it before the first hook runs, and a
        dispatcher that unpacks its own dependency out of a variadic bag hides
        the one argument it cannot do without.  It is still handed to the hook
        last, where every hook signature expects it.
        """
        for interceptor in self._list_for(kind):
            handler = getattr(interceptor, method, None)
            if handler is None:
                continue
            if not await _runs_for(interceptor, context):
                continue
            if safe:
                try:
                    await handler(*args, context)
                except Exception:  # noqa: BLE001 — interceptor must never break the flow
                    self._log_unexpected(interceptor, method, args[0])
            else:
                try:
                    await handler(*args, context)
                except InterceptorError:
                    raise
                except Exception:  # logged with the interceptor's name, then re-raised
                    self._log_unexpected(interceptor, method, args[0])
                    raise

    @staticmethod
    def _log_unexpected(
        interceptor: Any, method: str, entity_id: UUID | None = None
    ) -> None:
        """Log a failing hook with the module it came from.

        The class name alone was not actionable: the pipeline is global, so
        a bare interceptor name in the log named no owner and no module to
        switch off.  Called from inside an ``except`` block — that is what
        makes ``logger.exception`` carry the traceback.
        """
        logger.exception(
            '%s interceptor %s raised an unexpected error (module=%s%s)',
            method,
            type(interceptor).__name__,
            _module_of(interceptor) or 'unknown',
            f', entity_id={entity_id}' if entity_id is not None else '',
        )

    # ------------------------------------------------------------------
    # Item pipeline
    # ------------------------------------------------------------------

    async def run_before_item_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return await self._create('item', 'before_create', data, context)

    async def run_before_item_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return await self._update('item', 'before_update', item_id, changes, context)

    async def run_before_item_delete(
        self, item_id: UUID, context: ModuleContext
    ) -> None:
        await self._void('item', 'before_delete', context, item_id)

    async def run_before_item_purge(
        self, item_id: UUID, context: ModuleContext
    ) -> None:
        await self._void('item', 'before_purge', context, item_id)

    async def run_after_item_create(
        self, item_id: UUID, data: dict[str, Any], context: ModuleContext
    ) -> None:
        await self._void('item', 'after_create', context, item_id, data, safe=True)

    async def run_after_item_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> None:
        await self._void('item', 'after_update', context, item_id, changes, safe=True)

    async def run_after_item_delete(
        self, item_id: UUID, context: ModuleContext
    ) -> None:
        await self._void('item', 'after_delete', context, item_id, safe=True)

    async def run_before_item_consume(
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        await self._void('item', 'before_consume', context, item_id, quantity)

    async def run_after_item_consume(
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        await self._void('item', 'after_consume', context, item_id, quantity, safe=True)

    async def run_before_item_discard(
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        await self._void('item', 'before_discard', context, item_id, quantity)

    async def run_after_item_discard(
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        await self._void('item', 'after_discard', context, item_id, quantity, safe=True)

    # ------------------------------------------------------------------
    # Storage pipeline
    # ------------------------------------------------------------------

    async def run_before_storage_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return await self._create('storage', 'before_create', data, context)

    async def run_before_storage_update(
        self, storage_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return await self._update(
            'storage', 'before_update', storage_id, changes, context
        )

    async def run_before_storage_delete(
        self, storage_id: UUID, context: ModuleContext
    ) -> None:
        await self._void('storage', 'before_delete', context, storage_id)

    async def run_after_storage_create(
        self, storage_id: UUID, data: dict[str, Any], context: ModuleContext
    ) -> None:
        await self._void(
            'storage', 'after_create', context, storage_id, data, safe=True
        )

    async def run_after_storage_update(
        self, storage_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> None:
        await self._void(
            'storage', 'after_update', context, storage_id, changes, safe=True
        )

    async def run_after_storage_delete(
        self, storage_id: UUID, context: ModuleContext
    ) -> None:
        await self._void('storage', 'after_delete', context, storage_id, safe=True)

    # ------------------------------------------------------------------
    # Category pipeline
    # ------------------------------------------------------------------

    async def run_before_category_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return await self._create('category', 'before_create', data, context)

    async def run_before_category_update(
        self, category_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return await self._update(
            'category', 'before_update', category_id, changes, context
        )

    async def run_before_category_delete(
        self, category_id: UUID, context: ModuleContext
    ) -> None:
        await self._void('category', 'before_delete', context, category_id)

    async def run_after_category_create(
        self, category_id: UUID, data: dict[str, Any], context: ModuleContext
    ) -> None:
        await self._void(
            'category', 'after_create', context, category_id, data, safe=True
        )

    async def run_after_category_update(
        self, category_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> None:
        await self._void(
            'category', 'after_update', context, category_id, changes, safe=True
        )

    async def run_after_category_delete(
        self, category_id: UUID, context: ModuleContext
    ) -> None:
        await self._void('category', 'after_delete', context, category_id, safe=True)


interceptor_pipeline = InterceptorPipeline()
