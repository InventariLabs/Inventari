"""Unit tests for event deprecations + module event enums."""

import logging
import tomllib
from pathlib import Path

import pytest

from app.core._event_bus import event_bus
from app.core._event_deprecations import (
    DEPRECATED_EVENTS,
    _warned_once,
    get_deprecation,
    warn_if_deprecated,
)
from app.core._event_types import SystemEvent
from app.core.contracts.events import EventPayload


def _backend_version() -> tuple[int, ...]:
    pyproject = Path(__file__).resolve().parents[2] / 'pyproject.toml'
    data = tomllib.loads(pyproject.read_text())
    return tuple(int(part) for part in data['project']['version'].split('.'))


#: What each module owns, and the exact string it is on the wire. These
#: nine used to be spelled twice — once here, once as a ``SystemEvent``
#: member parked in the core table — and the core spelling was removed
#: before the repository went public.
_MODULE_OWNED_EVENTS = {
    'app.modules.warehouse.events:DocumentEvent': {
        'CONFIRMED': 'document.confirmed',
        'COMPLETED': 'document.completed',
        'CANCELLED': 'document.cancelled',
    },
    'app.modules.purchase_orders.events:PurchaseOrderEvent': {
        'CONFIRMED': 'purchase_order.confirmed',
        'COMPLETED': 'purchase_order.completed',
        'CANCELLED': 'purchase_order.cancelled',
        'RECEIPT_CREATED_FROM_PO': 'receipt.created_from_po',
    },
    'app.modules.equipment.events:EquipmentEvent': {
        'CHECKOUT': 'equipment.checkout',
        'CHECKIN': 'equipment.checkin',
    },
}


class TestModuleEventEnums:
    """The vertical events live in their modules — and only there."""

    @pytest.mark.parametrize('target', sorted(_MODULE_OWNED_EVENTS))
    def test_the_module_enum_carries_the_wire_names(self, target):
        import importlib

        module_path, enum_name = target.split(':')
        enum = getattr(importlib.import_module(module_path), enum_name)
        for member, wire_name in _MODULE_OWNED_EVENTS[target].items():
            assert getattr(enum, member).value == wire_name

    def test_the_core_table_no_longer_spells_them(self):
        """The removal that mattered: no second spelling in core.

        Nothing on the wire moved when these left ``SystemEvent`` — the
        module enums are ``StrEnum`` carrying the identical strings — which
        is exactly why the removal was safe to make without a window and
        why a re-added member would be invisible to every other test here.
        """
        core_values = {e.value for e in SystemEvent}
        for owned in _MODULE_OWNED_EVENTS.values():
            for wire_name in owned.values():
                assert wire_name not in core_values, (
                    f'{wire_name} is back in SystemEvent. It belongs to a '
                    f'module; core listing it is the duplicate spelling that '
                    f'was removed.'
                )

    def test_the_webhook_catalogue_did_not_lose_a_name(self):
        """The set a webhook may subscribe to is unchanged by the removal.

        ``valid_event_types`` unions the payload registry with
        ``SystemEvent``, and all nine sit in the core payload table — the
        first half of that union. So the core enum was the *second* place
        each name appeared, never the only one. This is the assertion that
        makes the removal safe rather than merely plausible; without it the
        reasoning rests on reading two files and believing the reading.
        """
        from app.modules.webhooks.schemas import valid_event_types

        allowed = valid_event_types()
        for owned in _MODULE_OWNED_EVENTS.values():
            for wire_name in owned.values():
                assert wire_name in allowed, wire_name

    def test_a_module_event_is_still_subscribable_by_its_string(self):
        """Removing the core member must not narrow what may be subscribed.

        ``_validate_event_name`` waves through anything in ``SystemEvent``
        and otherwise demands ``<module>.<event>``. All nine satisfy the
        convention on their own, so losing the core spelling costs nothing
        — this test is what says so.
        """
        from app.core.public_api.events import _validate_event_name

        for owned in _MODULE_OWNED_EVENTS.values():
            for wire_name in owned.values():
                _validate_event_name(wire_name)


class TestDeprecationRegistry:
    def test_the_removed_aliases_are_not_registered_any_more(self):
        """They are not deprecated — they are gone, and the register agrees.

        ``item.consumed``/``item.discarded`` left ``SystemEvent`` and the
        payload table without a window; a stale entry here would keep
        ``warn_if_deprecated`` logging about a name nothing emits every
        time something fired it.
        """
        for alias in ('item.consumed', 'item.discarded'):
            assert get_deprecation(alias) is None, alias

    def test_the_vertical_aliases_are_no_longer_deprecations(self):
        """They are not deprecated — they are gone, and the registry agrees.

        A stale entry here would keep ``warn_if_deprecated`` logging about a
        module's own event every time it fires.
        """
        for owned in _MODULE_OWNED_EVENTS.values():
            for wire_name in owned.values():
                assert get_deprecation(wire_name) is None, wire_name

    def test_neutral_events_not_deprecated(self):
        assert get_deprecation('item.created') is None
        assert get_deprecation('module.enabled') is None

    def test_expiry_not_reached(self):
        """Fails when the removal release ships — clean up or bump expiry.

        Vacuous while the register stands empty, and exactly the guard it
        names the moment the next deprecation is entered.
        """
        current = _backend_version()
        for event, deprecation in DEPRECATED_EVENTS.items():
            removal = tuple(int(p) for p in deprecation.removal_release.split('.'))
            assert current < removal, (
                f'{event}: removal release {deprecation.removal_release} reached '
                f'(current {".".join(str(p) for p in current)}) — remove the alias '
                f'or extend the expiry with a justification'
            )


class TestDeprecationWarning:
    @pytest.fixture
    def _synthetic_deprecation(self, monkeypatch):
        """Register a throwaway alias so the warn-once path is measurable.

        The register stands empty — nothing in the tree is deprecated any
        more — so the machinery's only honest test double is an entry the
        test itself adds and removes.
        """
        from app.core._event_deprecations import EventDeprecation

        monkeypatch.setitem(
            DEPRECATED_EVENTS,
            'item.consumed',
            EventDeprecation('item.consumed', 'item.used', 'test-only synthetic entry'),
        )
        yield

    def test_warns_once_per_event(self, caplog, _synthetic_deprecation):
        _warned_once.discard('item.consumed')
        with caplog.at_level(logging.WARNING):
            warn_if_deprecated('item.consumed')
            warn_if_deprecated('item.consumed')
        warnings = [r for r in caplog.records if 'item.consumed' in r.message]
        assert len(warnings) == 1

    def test_no_warning_for_current_events(self, caplog):
        with caplog.at_level(logging.WARNING):
            warn_if_deprecated('item.created')
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    @pytest.mark.asyncio
    async def test_bus_emit_warns_for_deprecated_event(
        self, caplog, _synthetic_deprecation
    ):
        _warned_once.discard('item.consumed')
        with caplog.at_level(logging.WARNING):
            await event_bus.emit(
                'item.consumed',
                EventPayload(quantity=1, organization_id='org-1', user_id='u-1'),
            )
        assert any('deprecated event' in r.message for r in caplog.records)


def test_a_malformed_event_name_is_a_contract_violation_not_a_refusal():
    from app.core.exceptions import ContractViolationError
    from app.core.public_api.events import _validate_event_name

    with pytest.raises(ContractViolationError, match='Invalid event name'):
        _validate_event_name('NotNamespaced')
