"""Base event payload contracts.

These bases were moved out of ``app.core._event_types`` so
that every event contract lives in ``app.core.contracts.events``. The old
module re-exports them for backward compatibility.

``extra='allow'`` is kept on the base for the transition period: several
legacy emitters still attach ORM objects to payloads. Per-event payload
models in ``_payloads.py`` declare the stable, typed contract fields while
tolerating those transitional extras.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EventPayload(BaseModel):
    """Base class for all events passed through the unified EventBus."""

    model_config = ConfigDict(extra='allow')


class TenantEventPayload(EventPayload):
    """Base class for events that belong to a specific tenant (organization)."""

    organization_id: str


class EventValidationError(ValueError):
    """Raised when an event payload fails validation against its registered type."""

    def __init__(self, event_name: str, details: object) -> None:
        self.event_name = event_name
        self.details = details
        super().__init__(f'Invalid payload for event {event_name!r}: {details}')
