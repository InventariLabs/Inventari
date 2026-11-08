from __future__ import annotations

from abc import ABC
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.context import ModuleContext

logger = get_logger(__name__)


class InterceptorError(Exception):
    """Raised by interceptors to block an operation with a user-visible message.

        ``details`` carries structured context (e.g. a purge blocker list) that
        routers surface verbatim in the error envelope — see the purge 409 shape
    . It is optional and defaults to ``None`` for existing callers.
    """

    def __init__(
        self,
        message: str,
        error_code: str = 'INTERCEPTOR_BLOCKED',
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.details = details
        super().__init__(message)


class ItemInterceptor(ABC):  # noqa: B024 — every hook has a default
    """Base class for interceptors that hook into item CRUD operations.

    Every hook has a default that lets the operation through unchanged, as
    on the storage and category bases, so a subclass overrides only the hooks
    it needs.

    Contract of ``after_*`` hooks: they run after the write has been
    ``flush()``-ed but **before commit**, inside the same DB transaction as
    the operation — services only flush; ``get_async_db`` teardown commits.
    They are read-only and must NOT be used for external side effects
    (webhook / email / print / SMS) — use the EventBus for those (ADR-007).
    An event that must agree with the write goes through the outbox
    (``emit_transactional``), which commits or rolls back with it.
    """

    #: Lower value = executed first in the pipeline.
    priority: int = 100

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Called before item creation.

        Receives mutable item data dict. Return the (possibly modified) dict.
        Raise :class:`InterceptorError` to abort the operation.
        """
        return data

    async def before_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Called before item update.

        Receives mutable changes dict. Return the (possibly modified) dict.
        Raise :class:`InterceptorError` to abort the operation.
        """
        return changes

    async def before_delete(  # noqa: B027
        self, item_id: UUID, context: ModuleContext
    ) -> None:
        """Called before item deletion.

        Raise :class:`InterceptorError` to abort the operation.
        """
        ...

    async def before_purge(  # noqa: B027
        self, item_id: UUID, context: ModuleContext
    ) -> None:
        """Called before an archived item is permanently purged.

        Raise :class:`InterceptorError` to abort the operation. Only fires on
        the irreversible path — the soft delete keeps its own
        ``before_delete`` hook, so modules can veto a purge (posted documents,
        stock-take evidence) without blocking everyday archiving.
        """
        ...

    async def after_create(  # noqa: B027
        self, item_id: UUID, data: dict[str, Any], context: ModuleContext
    ) -> None:
        """Called after the item write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        Exceptions are logged and swallowed — they must not break the
        request after the write has been flushed.
        """
        ...

    async def after_update(  # noqa: B027
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> None:
        """Called after the item write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        Exceptions are logged and swallowed — they must not break the
        request after the write has been flushed.
        """
        ...

    async def after_delete(  # noqa: B027
        self, item_id: UUID, context: ModuleContext
    ) -> None:
        """Called after the item write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        Exceptions are logged and swallowed — they must not break the
        request after the write has been flushed.
        """
        ...

    async def before_consume(  # noqa: B027
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        """Called before item consumption.

        Raise :class:`InterceptorError` to abort (e.g. item is currently lent out).
        """

    async def after_consume(  # noqa: B027
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        """Called after the item write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        Exceptions are logged and swallowed — they must not break the
        request after the write has been flushed.
        """

    async def before_discard(  # noqa: B027
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        """Called before item discard.

        Raise :class:`InterceptorError` to abort.
        """

    async def after_discard(  # noqa: B027
        self, item_id: UUID, quantity: Decimal, context: ModuleContext
    ) -> None:
        """Called after the item write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        Exceptions are logged and swallowed — they must not break the
        request after the write has been flushed.
        """


class StorageInterceptor(ABC):  # noqa: B024
    """Base class for interceptors that hook into storage location CRUD operations.

    ``after_*`` hooks run after the write has been flushed but before commit,
    in the same transaction; they are read-only and must not be used for
    external side effects — use the EventBus (ADR-007).
    """

    #: Lower value = executed first in the pipeline.
    priority: int = 100

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Called before storage location creation. Return modified data dict."""
        return data

    async def before_update(
        self, storage_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Called before storage location update. Return modified changes dict."""
        return changes

    async def before_delete(  # noqa: B027
        self, storage_id: UUID, context: ModuleContext
    ) -> None:
        """Called before storage location deletion. Raise InterceptorError to block."""
        ...

    async def after_create(  # noqa: B027
        self, storage_id: UUID, data: dict[str, Any], context: ModuleContext
    ) -> None:
        """Called after the write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        """

    async def after_update(  # noqa: B027
        self, storage_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> None:
        """Called after the write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        """

    async def after_delete(  # noqa: B027
        self, storage_id: UUID, context: ModuleContext
    ) -> None:
        """Called after the write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        """


class CategoryInterceptor(ABC):  # noqa: B024
    """Base class for interceptors that hook into category CRUD operations.

    ``after_*`` hooks run after the write has been flushed but before commit,
    in the same transaction; they are read-only and must not be used for
    external side effects — use the EventBus (ADR-007).
    """

    #: Lower value = executed first in the pipeline.
    priority: int = 100

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Called before category creation. Return modified data dict."""
        return data

    async def before_update(
        self, category_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Called before category update. Return modified changes dict."""
        return changes

    async def before_delete(  # noqa: B027
        self, category_id: UUID, context: ModuleContext
    ) -> None:
        """Called before category deletion. Raise InterceptorError to block."""
        ...

    async def after_create(  # noqa: B027
        self, category_id: UUID, data: dict[str, Any], context: ModuleContext
    ) -> None:
        """Called after the write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        """

    async def after_update(  # noqa: B027
        self, category_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> None:
        """Called after the write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        """

    async def after_delete(  # noqa: B027
        self, category_id: UUID, context: ModuleContext
    ) -> None:
        """Called after the write has been flushed (pre-commit, same transaction).

        Read-only. No external side effects — use the EventBus (ADR-007).
        """
