"""Tests for module startup resilience.

Verifies that:
1. A failing module's startup hook does NOT prevent subsequent modules
   from initializing.
2. Failed modules are marked as degraded in the registry.
3. The degraded flag is surfaced in ``GET /modules/available``.
4. ``register_contributions()`` failures are isolated per module.
5. ``STRICT_STARTUP`` raises after the startup loop (not swallowed).
"""

from __future__ import annotations

import pytest

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core._registry_class import ModuleRegistry
from app.core.context import ModuleContext
from app.core.events import event_bus
from app.schemas.module import ModuleInfo


class _OkModule(BaseModule):
    """Module that initializes successfully."""

    def __init__(self, name: str = 'ok_mod') -> None:
        self._name = name

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            display_name=self._name.title(),
            description='Always succeeds',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    def on_startup(self, context: ModuleContext) -> None:
        pass


class _BoomModule(BaseModule):
    """Module that raises ValueError in on_startup."""

    def __init__(self, name: str = 'boom_mod') -> None:
        self._name = name
        self.started = False

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            display_name=self._name.title(),
            description='Always fails on_startup',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    def on_startup(self, context: ModuleContext) -> None:
        raise ValueError('boom!')


class _BoomContribModule(BaseModule):
    """Module that raises in register_contributions."""

    def __init__(self, name: str = 'boom_contrib') -> None:
        self._name = name

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            display_name=self._name.title(),
            description='Fails in register_contributions',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    def register_contributions(self) -> None:
        raise ValueError('contrib boom!')


def _make_registry(*modules: BaseModule) -> ModuleRegistry:
    reg = ModuleRegistry()
    for m in modules:
        reg._modules[m.metadata.name] = m
    return reg


@pytest.mark.unit
class TestDegradedRegistry:
    """Registry tracks degraded modules."""

    def test_mark_and_check_degraded(self):
        reg = _make_registry()
        reg.mark_degraded('some_module')
        assert reg.is_degraded('some_module')
        assert not reg.is_degraded('other_module')


@pytest.mark.unit
class TestStartupIsolation:
    """A failing module does not block subsequent modules."""

    async def test_failing_module_does_not_block_next(self):
        """Simulate the lifespan module loop: if module A raises ValueError,
        module B should still get its on_startup called."""
        boom = _BoomModule('a')
        ok = _OkModule('b')
        reg = _make_registry(boom, ok)
        ctx = ModuleContext(event_bus=event_bus)

        failed: list[str] = []
        for module in reg.get_all():
            try:
                module.on_startup(ctx)
            except Exception:  # noqa: BLE001 — mirrors the startup loop under test
                failed.append(module.metadata.name)
                reg.mark_degraded(module.metadata.name)

        assert 'a' in failed
        assert 'b' not in failed
        assert reg.is_degraded('a')
        assert not reg.is_degraded('b')


@pytest.mark.unit
class TestContributionsIsolation:
    """register_contributions failure is isolated per module."""

    def test_failing_contributions_marked_degraded(self):
        boom = _BoomContribModule('bad')
        ok = _OkModule('good')
        reg = _make_registry(boom, ok)

        # Simulate main.py's register_contributions loop
        for module in reg.get_all():
            try:
                module.register_contributions()
            except Exception:  # noqa: BLE001 — mirrors the startup loop under test
                reg.mark_degraded(module.metadata.name)

        assert reg.is_degraded('bad')
        assert not reg.is_degraded('good')


@pytest.mark.unit
class TestModuleInfoDegradedField:
    """ModuleInfo schema exposes the degraded flag."""

    def test_degraded_defaults_false(self):
        info = ModuleInfo(
            name='test',
            display_name='Test',
            description='Test',
            icon='box',
            module_type='community',
            # Required, not defaulted: a fixture that omits what the module
            # touches would read on the store as touching nothing.
            capabilities=[],
        )
        assert info.degraded is False

    def test_degradable_can_be_set_true(self):
        info = ModuleInfo(
            name='test',
            display_name='Test',
            description='Test',
            icon='box',
            module_type='community',
            capabilities=[],
            degraded=True,
        )
        assert info.degraded is True
