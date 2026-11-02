"""Unit tests for the event payload registry."""

from enum import Enum

import pytest

from app.core._event_types import SystemEvent
from app.core.contracts.events import (
    EVENT_PAYLOAD_TYPES,
    EventPayload,
    EventValidationError,
    ItemQuantityEventPayload,
    TenantEventPayload,
    get_payload_type,
    validate_event_payload,
)


def _module_event_names() -> set[str]:
    """Collect event names declared in module-owned ``events.py`` enums.

    Module-scoped events are first-class citizens of the registry
    but deliberately do NOT live in core ``SystemEvent`` — the registry test
    must treat them as known.
    """
    import importlib
    import pkgutil

    import app.modules

    names: set[str] = set()
    for mod in pkgutil.iter_modules(app.modules.__path__):
        try:
            events_mod = importlib.import_module(f'app.modules.{mod.name}.events')
        except ModuleNotFoundError:
            continue
        for obj in vars(events_mod).values():
            if isinstance(obj, type) and issubclass(obj, Enum):
                names.update(e.value for e in obj)
    return names


class TestRegistryCoverage:
    def test_every_system_event_has_a_registered_payload_type(self):
        missing = [e.value for e in SystemEvent if e.value not in EVENT_PAYLOAD_TYPES]
        assert missing == []

    def test_registry_has_no_unknown_events(self):
        known = {e.value for e in SystemEvent} | _module_event_names()
        unknown = [name for name in EVENT_PAYLOAD_TYPES if name not in known]
        assert unknown == []

    def test_get_payload_type_returns_none_for_unknown_event(self):
        assert get_payload_type('no.such.event') is None


class TestValidateEventPayload:
    def test_valid_payload_returns_typed_instance(self):
        payload = validate_event_payload(
            'item.used',
            {
                'organization_id': 'org-1',
                'item': {'id': 'x'},
                'quantity': 2.5,
                'user_id': 'u-1',
            },
        )
        assert isinstance(payload, ItemQuantityEventPayload)
        assert payload.quantity == 2.5

    def test_missing_required_field_rejected(self):
        with pytest.raises(EventValidationError) as exc_info:
            validate_event_payload('item.deleted', {'organization_id': 'org-1'})
        assert exc_info.value.event_name == 'item.deleted'

    def test_wrong_field_type_rejected(self):
        with pytest.raises(EventValidationError):
            validate_event_payload(
                'item.used',
                {'organization_id': 'org-1', 'quantity': 'a lot', 'user_id': 'u-1'},
            )

    def test_validation_error_is_value_error(self):
        with pytest.raises(ValueError):
            validate_event_payload('document.completed', {'organization_id': 'o'})

    def test_transitional_extras_tolerated(self):
        """Legacy ORM-ish extras must not break validation (extra='allow')."""

        class FakeORM:
            pass

        payload = validate_event_payload(
            'item.created',
            {'organization_id': 'o', 'item': FakeORM(), 'user': FakeORM()},
        )
        assert isinstance(payload, EventPayload)

    def test_unknown_event_fails_open_tenant(self):
        payload = validate_event_payload(
            'custom.thing', {'organization_id': 'o', 'x': 1}
        )
        assert isinstance(payload, TenantEventPayload)

    def test_unknown_event_fails_open_plain(self):
        payload = validate_event_payload('custom.thing', {'x': 1})
        assert type(payload) is EventPayload

    def test_payload_instance_passthrough_for_unknown_event(self):
        original = EventPayload(x=1)
        assert validate_event_payload('custom.thing', original) is original


class TestBackwardCompatibility:
    def test_event_payload_identity_preserved(self):
        """app.core.events re-exports must be the same classes as contracts.events."""
        from app.core import events as core_events
        from app.core.contracts import events as contract_events

        assert core_events.EventPayload is contract_events.EventPayload
        assert core_events.TenantEventPayload is contract_events.TenantEventPayload

    def test_event_payload_importable_from_contracts_root(self):
        from app.core import contracts

        assert contracts.EventPayload is EventPayload
        assert contracts.TenantEventPayload is TenantEventPayload
