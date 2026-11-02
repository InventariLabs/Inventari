from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core._event_bus import event_bus
from app.core._event_types import (
    EventPayload,
    SystemEvent,
    TenantEventPayload,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    'EventPayload',
    'SystemEvent',
    'TenantEventPayload',
    'emit_safe',
    'emit_transactional_safe',
    'event_bus',
]


async def emit_safe(
    event: SystemEvent | str,
    payload: Mapping[str, Any] | EventPayload,
    *,
    label: str = '',
) -> None:
    """Emit *event*, logging and swallowing any delivery failure.

    Event publication is a side effect of the business operation, never a
    precondition for it: a broken subscriber must not roll back a checkout, a
    partner deactivation or a document transition.

    Note what is *not* covered: the payload is built by the caller, so a bug
    there (a missing key, a bad type) raises before this function is entered
    and fails loudly. That is deliberate — the hand-rolled ``try`` blocks this
    replaces wrapped payload construction too, which meant a coding mistake in
    the payload was logged at WARNING and silently dropped the event.

    Goes through ``core_api.events`` (dedup 4.5), so the payload is validated
    against the registry and coerced to its registered contract type. Pass a
    plain mapping or an instance of the event's registered contract class —
    both work. What the registry rejects is a *generic* ``EventPayload`` /
    ``TenantEventPayload`` instance where a specific contract type is
    registered, because pydantic will not re-validate one model class into
    another.

    ``label`` names the event in the log line when the caller wants something
    more readable than the raw enum value.

    The ``core_api`` import is function-local: ``app.core.public_api`` imports
    plenty of ``app.core.*`` and importing it at module scope here would be a
    cycle waiting to happen.
    """
    from app.core.public_api import core_api

    try:
        await core_api.events.emit_async(event, payload)
    except Exception as exc:  # emission must never break the caller
        logger.warning('Failed to emit %s: %s', label or event, exc, exc_info=True)


async def emit_transactional_safe(
    db: AsyncSession,
    event: SystemEvent | str,
    payload: Mapping[str, Any] | EventPayload,
    *,
    label: str = '',
) -> None:
    """Outbox-backed :func:`emit_safe` — publishes on the caller's transaction.

    Same swallow-and-log contract. Separate from :func:`emit_safe` because the
    underlying primitive is different: this one enrols the event in the outbox
    so a crash between commit and publish cannot lose it, and the caller must
    not have committed yet.
    """
    from app.core.public_api import core_api

    try:
        await core_api.events.emit_transactional_async(db, event, payload)
    except Exception as exc:  # emission must never break the caller
        logger.warning('Failed to emit %s: %s', label or event, exc, exc_info=True)
