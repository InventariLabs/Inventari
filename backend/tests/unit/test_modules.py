"""
Tests for core/modules.py require_module consistency.

Ensures the hardcoded always-enabled module list in require_module()
is consistent with TRUSTED_CORE_MODULES from module_registry.
"""

from app.core.module_registry import TRUSTED_CORE_MODULES


class TestModuleListConsistency:
    """Verify that always-enabled modules are a subset of TRUSTED_CORE_MODULES."""

    def test_always_enabled_modules_in_trusted(self):
        from app.core.modules import ALWAYS_ENABLED_MODULES

        missing = ALWAYS_ENABLED_MODULES - TRUSTED_CORE_MODULES
        assert not missing, (
            f'Platform-critical modules missing from TRUSTED_CORE_MODULES: {missing}'
        )

    def test_trusted_contains_all_always_enabled(self):
        from app.core.modules import ALWAYS_ENABLED_MODULES

        trusted_missing: set[str] = ALWAYS_ENABLED_MODULES - TRUSTED_CORE_MODULES
        assert not trusted_missing, (
            f'TRUSTED_CORE_MODULES is missing these always-enabled modules: '
            f'{trusted_missing}'
        )
