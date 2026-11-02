"""
Integration test: webhooks runtime settings read from ``module:webhooks``.

The pre-P1.4 path read ``org.settings['webhooks']`` (flat). P1.4 moves
this to ``core_api.settings.get_async(db, org_id, 'webhooks')`` so the
same namespace is honoured by PUT /modules/webhooks/settings.

A one-time migration in ``WebhooksModule.on_startup_async`` copies any
existing flat-key values into the namespace so existing deployments
keep their settings.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _make_org(settings: dict[str, Any]) -> MagicMock:
    org = MagicMock()
    org.id = uuid4()
    org.settings = settings
    return org


def _make_db() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runtime_read_finds_settings_under_module_namespace() -> None:
    org_id = uuid4()
    org = _make_org({'module:webhooks': {'circuit_breaker_threshold': 17}})

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=org)

    from app.core.public_api import core_api as _core_api

    threshold = await _core_api.settings.get_async(
        db, org_id, 'webhooks', 'circuit_breaker_threshold'
    )
    assert threshold == 17


@pytest.mark.asyncio
@pytest.mark.integration
async def test_one_time_migration_copies_flat_to_namespaced() -> None:
    org_id = uuid4()
    settings: dict[str, Any] = {
        'webhooks': {
            'circuit_breaker_threshold': 25,
            'log_retention_days': 60,
        }
    }

    from app.modules.webhooks.migration import migrate_webhooks_settings

    new_settings = migrate_webhooks_settings(settings, org_id)

    assert new_settings is not None
    assert new_settings['module:webhooks']['circuit_breaker_threshold'] == 25
    assert new_settings['module:webhooks']['log_retention_days'] == 60


@pytest.mark.asyncio
@pytest.mark.integration
async def test_migration_is_idempotent() -> None:
    org_id = uuid4()
    settings: dict[str, Any] = {
        'webhooks': {'circuit_breaker_threshold': 25},
        'module:webhooks': {'circuit_breaker_threshold': 99},
    }

    from app.modules.webhooks.migration import migrate_webhooks_settings

    assert migrate_webhooks_settings(settings, org_id) is None
    assert settings['module:webhooks']['circuit_breaker_threshold'] == 99
