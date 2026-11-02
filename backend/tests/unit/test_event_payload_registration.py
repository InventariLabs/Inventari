"""Modules declare their own event payload contracts at runtime.

Before this, the payload registry was a static table in core, so a module
event either had no contract or forced core to know about the module. The
runtime registry keeps the two apart: core owns its names, a module owns
everything under its own namespace.
"""

import pytest

from app.core.contracts.events import (
    EventPayload,
    RecipeCreatedPayload,
    TenantEventPayload,
    get_payload_type,
    register_payload,
    registered_payloads,
    validate_event_payload,
)
from app.core.contracts.events import _registry as registry


class WarrantyExpiredPayload(TenantEventPayload):
    asset_id: str


class OtherPayload(TenantEventPayload):
    asset_id: str


@pytest.fixture(autouse=True)
def _clean_runtime_registry():
    """Registration is global state; do not leak it into other tests."""
    saved = dict(registry._RUNTIME_PAYLOAD_TYPES)
    registry._RUNTIME_PAYLOAD_TYPES.clear()
    yield
    registry._RUNTIME_PAYLOAD_TYPES.clear()
    registry._RUNTIME_PAYLOAD_TYPES.update(saved)


class TestRegisterPayload:
    def test_registered_event_gets_its_contract(self):
        register_payload('warranty.expired', WarrantyExpiredPayload)

        assert get_payload_type('warranty.expired') is WarrantyExpiredPayload

    def test_emit_time_validation_uses_the_registration(self):
        register_payload('warranty.expired', WarrantyExpiredPayload)

        payload = validate_event_payload(
            'warranty.expired',
            {'organization_id': 'org-1', 'asset_id': 'a-1'},
        )

        assert isinstance(payload, WarrantyExpiredPayload)
        assert payload.asset_id == 'a-1'

    def test_catalog_lists_runtime_registrations(self):
        register_payload('warranty.expired', WarrantyExpiredPayload)

        catalog = registered_payloads()

        assert catalog['warranty.expired'] is WarrantyExpiredPayload
        # Core entries survive alongside it.
        assert 'item.created' in catalog

    def test_re_registering_the_same_model_is_tolerated(self):
        """A module reload must not be an error."""
        register_payload('warranty.expired', WarrantyExpiredPayload)
        register_payload('warranty.expired', WarrantyExpiredPayload)

        assert get_payload_type('warranty.expired') is WarrantyExpiredPayload


class TestRegisterPayloadRefuses:
    @pytest.mark.parametrize(
        'name',
        ['expired', 'Warranty.Expired', 'warranty.', '.expired', 'a.b.c', '1.x'],
    )
    def test_unnamespaced_or_malformed_names(self, name):
        with pytest.raises(ValueError, match='namespaced'):
            register_payload(name, WarrantyExpiredPayload)

    def test_shadowing_a_core_event(self):
        """Core owns its names; a module redefining them would break subscribers."""
        with pytest.raises(ValueError, match='core event'):
            register_payload('item.created', WarrantyExpiredPayload)

    def test_redeclaring_a_core_event_with_the_same_model_is_a_no_op(self):
        """Transition release: a module re-declares its own event with the very
        class that lives in the core table until 0.10.0 — that is an ownership
        claim, not a shadowing attempt, and must not raise."""
        register_payload('recipe.created', RecipeCreatedPayload)
        register_payload('recipe.created', RecipeCreatedPayload)  # reload-safe

        assert get_payload_type('recipe.created') is RecipeCreatedPayload
        # The core table stays the source; nothing leaks into the runtime map.
        assert 'recipe.created' not in registry._RUNTIME_PAYLOAD_TYPES

    def test_redeclaring_a_core_event_with_a_different_model_is_refused(self):
        class RenegadePayload(TenantEventPayload):
            recipe_id: str

        with pytest.raises(ValueError, match='core event'):
            register_payload('recipe.created', RenegadePayload)

    def test_two_models_for_one_name(self):
        register_payload('warranty.expired', WarrantyExpiredPayload)

        with pytest.raises(ValueError, match='already registered'):
            register_payload('warranty.expired', OtherPayload)

    def test_a_model_that_is_not_a_payload(self):
        with pytest.raises(ValueError, match='EventPayload subclass'):
            register_payload('warranty.expired', dict)

    def test_unregistered_event_still_fails_open(self):
        """Unknown names keep passing through — fail-open for one release."""
        payload = validate_event_payload('nobody.knows', {'organization_id': 'o'})

        assert isinstance(payload, EventPayload)
