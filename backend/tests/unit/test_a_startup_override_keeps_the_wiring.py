"""A module that overrides ``on_startup`` without ``super()`` still gets wired.

The base ``on_startup`` used to be where the framework registered the
module's services and contributions and wired its interceptors. A module
author overriding the hook for a scheduled task of their own, and not
calling ``super()``, lost all three without a word: the module started,
its routes answered, and its interceptors were simply never run.

The startup walk now does the wiring itself, before the hook, so what the
module's own ``on_startup`` does or forgets cannot take it away.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.context import ModuleContext


class _ForgetfulModule(BaseModule):
    """Overrides ``on_startup`` the way an author in a hurry does."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='forgetful',
            version='1.0.0',
            display_name='Forgetful',
            description='overrides on_startup without super()',
            icon='box',
        )

    def register_routes(self) -> APIRouter:
        return APIRouter()

    def register_services(self, container: Any) -> None:
        self.calls.append('register_services')

    def register_contributions(self) -> None:
        self.calls.append('register_contributions')

    def _wire_interceptors(self) -> None:
        self.calls.append('wire_interceptors')

    def on_startup(self, context: ModuleContext) -> None:
        # No super(): the module's own work only.
        self.calls.append('on_startup')


class _Registry:
    """The slice of ModuleRegistry the startup walk touches."""

    def __init__(self, module: BaseModule) -> None:
        self._module = module

    def get_all(self) -> list[BaseModule]:
        return [self._module]

    async def check_module_version_async(self, module: BaseModule, db: Any) -> None:
        return None

    def mark_degraded(self, name: str) -> None:
        raise AssertionError(f'{name} failed to start')


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.mark.unit
async def test_the_startup_walk_wires_a_module_whose_hook_skips_super(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import _lifespan
    from app.core.events import event_bus

    module = _ForgetfulModule()
    monkeypatch.setattr('app.core.module_registry.module_registry', _Registry(module))
    monkeypatch.setattr('app.database.AsyncSessionLocal', _Session)

    failed = await _lifespan._initialize_modules(_lifespan._get_logger(), event_bus)

    assert failed == []
    assert module.calls == [
        'register_services',
        'register_contributions',
        'wire_interceptors',
        'on_startup',
    ]
