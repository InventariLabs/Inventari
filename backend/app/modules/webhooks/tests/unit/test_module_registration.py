"""Unit tests for WebhooksModule.on_startup task registration.

Guards against regressions that burned production: duplicate registration of
the retry/cleanup workers and the 1 Hz ``webhooks_settings_migration`` task
that looped forever in every worker. The migration now runs once at startup
as a fire-and-forget asyncio task.
"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.context import ModuleContext
from app.modules.webhooks.module import WebhooksModule

RegisterFn = Callable[..., None]


@pytest.fixture
def module() -> WebhooksModule:
    return WebhooksModule()


async def _startup(module: WebhooksModule, context: ModuleContext) -> None:
    module.on_startup(context)
    # Let the fire-and-forget migration task execute.
    await asyncio.sleep(0)


def _run_on_startup(
    module: WebhooksModule, captured: dict[str, timedelta] | None = None
) -> list[str]:
    """Run on_startup inside an event loop; return registered task names."""
    registered: list[str] = []

    def fake_register(
        name: str,
        interval: timedelta,
        handler: Any,
        module_name: str,
        is_persistent: bool = False,
    ) -> None:
        registered.append(name)
        if captured is not None:
            captured[name] = interval

    context = MagicMock(spec=ModuleContext)
    with (
        patch('app.core.scheduler.task_scheduler.register', side_effect=fake_register),
        patch.object(WebhooksModule, '_migrate_settings_worker', return_value=None),
    ):
        asyncio.run(_startup(module, context))
    return registered


@pytest.mark.unit
class TestWebhookTaskRegistration:
    def test_no_duplicate_task_keys(self, module: WebhooksModule) -> None:
        registered = _run_on_startup(module)
        assert len(registered) == len(set(registered)), (
            f'duplicate task registrations: {registered}'
        )

    def test_retry_and_cleanup_registered_persistent(
        self, module: WebhooksModule
    ) -> None:
        registered = _run_on_startup(module)
        assert 'webhooks_retry_failed' in registered
        assert 'webhooks_cleanup_logs' in registered

    def test_settings_migration_not_a_periodic_task(
        self, module: WebhooksModule
    ) -> None:
        registered = _run_on_startup(module)
        assert 'webhooks_settings_migration' not in registered

    def test_settings_migration_runs_once_at_startup(
        self, module: WebhooksModule
    ) -> None:
        context = MagicMock(spec=ModuleContext)
        migration = MagicMock(return_value=None)
        with (
            patch('app.core.scheduler.task_scheduler.register'),
            patch.object(
                WebhooksModule, '_migrate_settings_worker', side_effect=migration
            ),
        ):
            asyncio.run(_startup(module, context))
        migration.assert_called_once()

    def test_startup_without_running_loop_does_not_crash(
        self, module: WebhooksModule
    ) -> None:
        """on_startup outside an event loop must skip the one-shot migration."""
        context = MagicMock(spec=ModuleContext)
        with patch('app.core.scheduler.task_scheduler.register'):
            module.on_startup(context)  # no asyncio.run — no running loop


@pytest.mark.unit
class TestEventSubscriptions:
    """The module must subscribe to module-contributed events, not just the enum."""

    @staticmethod
    def _subscribed_events(module: WebhooksModule) -> list[str]:
        """What the module subscribes to, driven at the moment it now does.

        The subscription left ``on_startup`` — which runs in the middle of an
        alphabetical walk of the modules directory and cannot see what a
        later-named module contributes — for ``on_modules_ready``, which runs
        once the catalogue is complete. These tests care about the set of
        events rather than the moment, so they drive the hook the set is now
        taken in.
        """
        context = MagicMock(spec=ModuleContext)
        with (
            patch('app.core.scheduler.task_scheduler.register'),
            patch.object(WebhooksModule, '_migrate_settings_worker', return_value=None),
        ):
            asyncio.run(_startup(module, context))
        module.on_modules_ready(context)
        return [call.args[0] for call in context.subscribe.call_args_list]

    def test_subscribes_to_registry_events(self, module: WebhooksModule) -> None:
        """Without this, the API accepts a `recipe.created` webhook that never fires."""
        assert 'recipe.created' in self._subscribed_events(module)

    def test_still_subscribes_to_core_enum_events(self, module: WebhooksModule) -> None:
        assert 'item.created' in self._subscribed_events(module)

    def test_subscribes_once_per_event(self, module: WebhooksModule) -> None:
        """Names present in both the registry and the enum must not double-fire."""
        events = self._subscribed_events(module)
        assert len(events) == len(set(events))


@pytest.mark.unit
class TestRegistrationIntervals:
    def test_retry_interval_60s_cleanup_24h(self, module: WebhooksModule) -> None:
        captured: dict[str, timedelta] = {}
        _run_on_startup(module, captured)
        assert captured['webhooks_retry_failed'] == timedelta(seconds=60)
        assert captured['webhooks_cleanup_logs'] == timedelta(hours=24)
