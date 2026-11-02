"""Test that module trust lists remain consistent."""

import pytest

from app.core.module_registry import TRUSTED_CORE_MODULES
from app.core.modules import ALWAYS_ENABLED_MODULES, CORE_MODULES


@pytest.mark.unit
class TestModuleListsConsistency:
    def test_trusted_core_modules_not_empty(self):
        assert len(TRUSTED_CORE_MODULES) > 0

    def test_core_and_items_always_trusted(self):
        assert 'core' in TRUSTED_CORE_MODULES
        assert 'items' in TRUSTED_CORE_MODULES

    def test_trusted_modules_are_discoverable(self):
        from app.core.module_registry import module_registry

        if not module_registry.get_all():
            module_registry.discover_modules()

        discovered = {m.metadata.name for m in module_registry.get_all()}
        virtual_modules = {
            'core',
            'items',
            'locations',
            'categories',
            'announcements',
        }
        undiscovered = TRUSTED_CORE_MODULES - discovered - virtual_modules
        assert not undiscovered, (
            f'TRUSTED_CORE_MODULES contains modules not discovered: {undiscovered}'
        )

    def test_always_enabled_subset_of_core(self):
        assert ALWAYS_ENABLED_MODULES.issubset(CORE_MODULES)

    def test_core_modules_subset_of_trusted(self):
        assert CORE_MODULES.issubset(TRUSTED_CORE_MODULES)

    def test_no_food_specific_in_core_modules(self):
        assert 'nutrition' not in CORE_MODULES
        assert 'vision' not in CORE_MODULES
