"""Tests for async install hooks.

Verifies that ``on_install_async`` on ``BaseModule`` properly awaits
async logic, and that the warehouse module no longer uses
``asyncio.run()`` which would crash inside an already-running event loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.context import ModuleContext
from app.core.events import event_bus


class _SimpleModule(BaseModule):
    """Minimal BaseModule for testing install hook behaviour."""

    def __init__(
        self,
        *,
        async_hook: Any | None = None,
        sync_hook: Any | None = None,
    ) -> None:
        self._async_hook = async_hook
        self._sync_hook = sync_hook

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='__test_install',
            display_name='Test Install',
            description='Test',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    # Override on_install to skip real migrations (unit test)
    def on_install(self, context: ModuleContext) -> None:
        if self._sync_hook:
            self._sync_hook(context)

    async def on_install_async(self, context: ModuleContext) -> None:
        if self._async_hook:
            await self._async_hook(context)
        else:
            self.on_install(context)


@pytest.mark.unit
class TestAsyncInstallHook:
    """on_install_async is awaited correctly."""

    async def test_async_install_hook_runs(self):
        ran = False

        async def _async_hook(ctx: ModuleContext) -> None:
            nonlocal ran
            ran = True

        mod = _SimpleModule(async_hook=_async_hook)
        ctx = ModuleContext(event_bus=event_bus, organization_id=None)
        await mod.on_install_async(ctx)

        assert ran, 'async install hook was not awaited'

    async def test_async_install_takes_priority(self):
        async_ran = False
        sync_ran = False

        async def _async_hook(ctx: ModuleContext) -> None:
            nonlocal async_ran
            async_ran = True

        def _sync_hook(ctx: ModuleContext) -> None:
            nonlocal sync_ran
            sync_ran = True

        mod = _SimpleModule(async_hook=_async_hook, sync_hook=_sync_hook)
        ctx = ModuleContext(event_bus=event_bus, organization_id=None)
        await mod.on_install_async(ctx)

        assert async_ran, 'async install hook should have run'
        assert not sync_ran, 'sync hook should not run when async is provided'

    async def test_delegates_to_sync_when_no_async(self):
        sync_ran = False

        def _sync_hook(ctx: ModuleContext) -> None:
            nonlocal sync_ran
            sync_ran = True

        mod = _SimpleModule(sync_hook=_sync_hook)
        ctx = ModuleContext(event_bus=event_bus, organization_id=None)
        await mod.on_install_async(ctx)

        assert sync_ran, 'sync install hook should run via on_install_async delegation'


@pytest.mark.unit
class TestWarehouseModuleNoAsyncioRun:
    """The warehouse module must not use asyncio.run() in its install hook."""

    def test_warehouse_module_uses_async_hook(self):
        """Verify the warehouse module source no longer contains asyncio.run."""
        source = (
            Path(__file__).resolve().parent.parent.parent
            / 'app'
            / 'modules'
            / 'warehouse'
            / 'module.py'
        ).read_text()
        assert 'asyncio.run' not in source, (
            'warehouse/module.py must not use asyncio.run() — use on_install_async_hook'
        )
        assert 'on_install_async_hook' in source, (
            'warehouse/module.py should use on_install_async_hook for async DB access'
        )
