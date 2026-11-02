"""Module-safe event bus facade.

``core_api.events`` is the supported way for modules to emit and subscribe
to events. Unlike the raw ``event_bus`` singleton, every operation goes
through the payload registry (``app.core.contracts.events``):

- payloads of registered events are validated/coerced to their contract type
  — a bad payload is rejected with :class:`EventValidationError` at emit time
- event names must be namespaced (``<module>.<event>``) unless they are core
  ``SystemEvent`` values
- ``subscribe`` supports an optional per-organization filter
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core._event_bus import event_bus, handler_name
from app.core._event_types import SystemEvent
from app.core.contracts.events import (
    EventPayload,
    get_payload_type,
    register_payload,
    registered_payloads,
    validate_event_payload,
)
from app.core.exceptions import ContractViolationError
from app.core.logging import get_logger

logger = get_logger(__name__)

_EVENT_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')

_CORE_EVENT_NAMES = frozenset(e.value for e in SystemEvent)


def _event_value(event: SystemEvent | str) -> str:
    return event.value if isinstance(event, SystemEvent) else event


def _validate_event_name(event_name: str) -> None:
    """Enforce the ``<module>.<event>`` namespacing convention.

    Core ``SystemEvent`` values are always allowed; custom module events
    must be namespaced (e.g. ``rental.reservation_created``).

    Shape is all this checks. Who may *own* a name is enforced where the
    identity is known: ``register_payload`` refuses a claim on a loaded
    module's namespace, and ``event_bus.emit`` refuses an emission into a
    namespace the caller does not own (``app.core.module_identity``).
    """
    if event_name in _CORE_EVENT_NAMES:
        return
    if not _EVENT_NAME_PATTERN.match(event_name):
        raise ContractViolationError(
            f'Invalid event name {event_name!r}: custom events must follow '
            f'the "<module>.<event>" convention (lowercase, dot-separated).'
        )


def _build_payload(
    event_name: str,
    payload: Mapping[str, Any] | EventPayload,
) -> EventPayload:
    return validate_event_payload(event_name, payload)


class CoreEventsAPI:
    """Public Core API for validated event emission and subscription."""

    async def emit_async(
        self,
        event: SystemEvent | str,
        payload: Mapping[str, Any] | EventPayload,
    ) -> None:
        """Emit an event after validating its payload against the registry.

        Tenant events carry ``organization_id`` (str) inside the payload —
        same convention as the raw emitters. Raises
        :class:`EventValidationError` for registered events with an invalid
        payload, and ``ValueError`` for non-namespaced custom event names.
        Unregistered (but well-formed) events pass through with the
        permissive base payload.
        """
        event_name = _event_value(event)
        _validate_event_name(event_name)
        validated = _build_payload(event_name, payload)
        await event_bus.emit(event_name, validated)

    async def emit_transactional_async(
        self,
        db: AsyncSession,
        event: SystemEvent | str,
        payload: Mapping[str, Any] | EventPayload,
    ) -> None:
        """Outbox-backed emit riding the caller's transaction.

        Same validation as :meth:`emit_async`. The event is published by the outbox
        relay only after the surrounding commit (buffered + ``flush_pending_async``
        in TESTING). Callers must NOT commit before calling this.
        """
        event_name = _event_value(event)
        _validate_event_name(event_name)
        validated = _build_payload(event_name, payload)
        await event_bus.emit_transactional(db, event_name, validated)

    async def flush_pending_async(self, db: AsyncSession) -> None:
        """Dispatch TESTING-buffered transactional events after ``db.commit()``."""
        await event_bus.flush_pending(db)

    def subscribe(
        self,
        event: SystemEvent | str,
        handler: Callable[[EventPayload], Any],
        *,
        org_filter: UUID | str | None = None,
    ) -> None:
        """Subscribe to an event with payload coercion and optional org filter.

        The handler receives the payload coerced to the registered contract
        type (when one exists). When ``org_filter`` is given, events
        belonging to other organizations — or carrying no tenant — are
        skipped at dispatch time (consumer path). Payloads that fail
        coercion are logged and dropped (a bad message must not stall the
        consumer group).
        """
        event_name = _event_value(event)
        _validate_event_name(event_name)
        payload_type = get_payload_type(event_name)
        org = str(org_filter) if org_filter is not None else None

        async def wrapper(payload: EventPayload) -> None:
            coerced = payload
            if payload_type is not None and not isinstance(payload, payload_type):
                try:
                    coerced = payload_type.model_validate(payload.model_dump())
                except ValidationError as exc:
                    logger.error(
                        '[events] dropping %s payload failing contract validation: %s',
                        event_name,
                        exc,
                    )
                    return
            result = handler(coerced)
            if inspect.isawaitable(result):
                await result

        # The delivery log names the module's function, not this closure.
        event_bus.subscribe(
            event_name, wrapper, org_filter=org, name=handler_name(handler)
        )

    def register_payload(self, event_name: str, model: type[EventPayload]) -> None:
        """Declare the payload contract for one of this module's events.

        Call it from the module's ``on_startup``. Once registered, every emit of
        *event_name* is validated against *model*, so a subscriber can rely on
        the shape instead of probing a dict.

        The name must be namespaced ``<module>.<event>``; core event names are
        owned by the core contract and cannot be redefined with a different
        model. Re-declaring one with the identical class is a tolerated no-op
        for one release — that is how a module claims ownership of a contract
        that still lives in the core table until the planned move. A new name
        may not sit in another loaded module's namespace: the caller's identity
        (``app.core.module_identity``) is checked at the registry, so module
        foo cannot register ``bar.something`` and have every subscriber read
        it as bar's event.
        """
        register_payload(event_name, model)

    def registered_events(self) -> dict[str, str]:
        """Return ``{event_name: payload_type_name}`` for the event catalog.

        Includes payloads registered at runtime by modules, so the catalog
        answers "what can I subscribe to" rather than "what did core ship".
        """
        return {name: tp.__name__ for name, tp in sorted(registered_payloads().items())}
