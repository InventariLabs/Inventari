"""
End-to-end pattern validation for module feature toggles.

The toggle contract:
  1. A module declares a JSON Schema field in `get_settings_schema()`.
  2. A profile declares a preset value in `ProductProfile.module_config`.
  3. During onboarding / switch, the preset is written via
     `write_module_settings_async` after the module is enabled.

This test asserts all three legs of the contract hold for the
`recipes.enable_cost_calculation` pilot. It uses stubs so it does not
require the real `recipes` module to be loaded by the registry.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


class _StubRecipesModule:
    """Stand-in for the real `recipes` module."""

    def __init__(self, schema: dict | None, defaults: dict) -> None:
        self._schema = schema
        self._defaults = defaults

    @property
    def metadata(self) -> MagicMock:
        m = MagicMock()
        m.name = 'recipes'
        return m

    def get_settings_schema(self) -> dict | None:
        return self._schema

    def get_default_settings(self) -> dict:
        return self._defaults

    async def system_on_enable(
        self, org_id: str, db, *, user: Any | None = None
    ) -> None:
        return None


@pytest.fixture
def stubbed_recipes_module(monkeypatch):
    schema = {
        'type': 'object',
        'properties': {
            'enable_cost_calculation': {
                'type': 'boolean',
                'default': True,
                'title': 'Enable cost calculation',
            },
        },
        'additionalProperties': False,
    }
    defaults = {'enable_cost_calculation': True}
    recipes_stub = _StubRecipesModule(schema, defaults)

    async def _noop_async_enable(org_id, db):
        return None

    class _GenericNoopModule:
        def __init__(self, name: str) -> None:
            self._name = name

        @property
        def metadata(self) -> MagicMock:
            m = MagicMock()
            m.name = self._name
            return m

        def get_settings_schema(self) -> dict | None:
            return None

        def get_default_settings(self) -> dict:
            return {}

        async def system_on_enable(self, org_id, db, *, user=None) -> None:
            return None

    from app.core.module_registry import module_registry

    def fake_get(name: str):
        if name == 'recipes':
            return recipes_stub
        return _GenericNoopModule(name)

    monkeypatch.setattr(module_registry, 'get', fake_get)
    return recipes_stub


def _make_org(enabled_modules: list[str] | None = None) -> MagicMock:
    org = MagicMock()
    org.id = uuid4()
    org.enabled_modules = list(enabled_modules or [])
    org.settings = {}
    return org


@pytest.mark.asyncio
async def test_recipes_cost_toggle_schema_is_typed(stubbed_recipes_module) -> None:
    """The schema declares the field as a boolean with default True."""
    schema = stubbed_recipes_module.get_settings_schema()
    assert schema is not None
    field = schema['properties']['enable_cost_calculation']
    assert field['type'] == 'boolean'
    assert field['default'] is True


@pytest.mark.asyncio
async def test_food_home_preset_enables_recipe_cost(
    stubbed_recipes_module, monkeypatch
) -> None:
    """food_home.module_config.recipes.enable_cost_calculation is True."""
    from app.core.product_profiles import get_profile

    profile = get_profile('food_home')
    assert profile is not None
    assert (
        profile.module_config.get('recipes', {}).get('enable_cost_calculation') is True
    )


@pytest.mark.asyncio
async def test_equipment_wms_has_no_recipe_preset(
    stubbed_recipes_module,
) -> None:
    """equipment_wms is a procurement/equipment stack — recipes is not part of
    its ``default_modules``, so it must not declare a ``recipes``
    ``module_config`` override (such an entry is dead config that the
    onboarding service would skip with a warning)."""
    from app.core.product_profiles import get_profile

    profile = get_profile('equipment_wms')
    assert profile is not None
    assert 'recipes' not in profile.module_config


@pytest.mark.asyncio
async def test_clean_core_has_no_recipe_preset(
    stubbed_recipes_module,
) -> None:
    """clean_core does not override the toggle — defaults from the module apply."""
    from app.core.product_profiles import get_profile

    profile = get_profile('clean_core')
    assert profile is not None
    assert 'recipes' not in profile.module_config


@pytest.mark.asyncio
async def test_food_home_preset_is_applied_via_set_bulk(
    stubbed_recipes_module, monkeypatch
) -> None:
    """End-to-end: profile preset reaches the module settings write."""
    from app.core.product_profiles import get_profile
    from app.services import onboarding_service

    captured: dict[str, dict[str, object]] = {}

    async def fake_set_bulk(db, org_id, module_name, values):
        captured.setdefault(module_name, {}).update(values)

    monkeypatch.setattr(
        'app.services.module_settings_service.write_module_settings_async',
        fake_set_bulk,
    )

    # The profile's starting-location seeding needs a real
    # session; this test is about the config persistence path.
    async def fake_seed_locations(db, organization_id, user_id):
        return []

    monkeypatch.setattr(
        'app.services.storage._defaults.create_default_storage_locations_async',
        fake_seed_locations,
    )

    db = MagicMock()
    db.run_sync = AsyncMock(side_effect=lambda fn: fn(MagicMock()))
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    profile = get_profile('food_home')
    assert profile is not None
    org = _make_org()

    await onboarding_service.apply_onboarding_profile_async(
        db, org, 'food_home', profile=profile
    )

    assert captured.get('recipes', {}).get('enable_cost_calculation') is True
