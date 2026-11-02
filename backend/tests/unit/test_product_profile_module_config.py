"""
Unit tests for ProductProfile.module_config application during onboarding.

Profiles may declare ``module_config: {module_name: {key: value}}``.
After enabling each module, the onboarding service applies those
overrides via ``core_api.settings.set_bulk_async`` so the org starts
with sensible defaults rather than an empty settings blob.

Settings that fail schema validation are skipped with a log warning —
the org still gets the module enabled, just with default settings.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


class _StubModule:
    def __init__(self, name: str, schema):
        self._name = name
        self._schema = schema

    @property
    def metadata(self) -> MagicMock:
        m = MagicMock()
        m.name = self._name
        return m

    def get_settings_schema(self) -> dict | None:
        return self._schema

    async def system_on_enable(
        self, org_id: str, db, *, user: Any | None = None
    ) -> None:
        return None


@pytest.fixture
def patched_org_service():
    from app.services import _org_reads

    original = _org_reads.get_by_id_async
    yield
    _org_reads.get_by_id_async = original


@pytest.fixture
def restored_module_registry():
    """Snapshot and restore ``module_registry.get``.

    Tests in this module reassign the singleton's ``get`` to a stub lambda to
    drive the module-config logic without real modules. The reassignment must
    be restored, otherwise it leaks into later serial test runs and makes
    ``module_registry.get('equipment')`` return a schema-less stub — which
    silently skips the equipment ``module_config`` and breaks unrelated
    onboarding assertions.
    """
    from app.core.module_registry import module_registry

    original_get = module_registry.get
    yield
    module_registry.get = original_get  # type: ignore[method-assign]


def _make_org(enabled_modules: list[str] | None = None) -> MagicMock:
    org = MagicMock()
    org.id = uuid4()
    org.enabled_modules = list(enabled_modules or [])
    org.settings = {}
    return org


@pytest.mark.asyncio
async def test_module_config_is_persisted_for_each_module(
    patched_org_service,
    restored_module_registry,
) -> None:
    from app.core.module_registry import module_registry
    from app.core.product_profiles import ProductProfile
    from app.services import onboarding_service

    module_registry.get = lambda n: _StubModule(  # type: ignore[method-assign,return-value,assignment]
        n,
        {
            'type': 'object',
            'properties': {'threshold': {'type': 'integer', 'minimum': 1}},
        },
    )

    profile = ProductProfile(
        id='test',
        name='Test',
        description='desc',
        default_modules=['webhooks'],
        seed_profile='clean_core',
        module_config={
            'webhooks': {'threshold': 5},
        },
    )

    captured: dict[str, dict[str, object]] = {}

    async def fake_set_bulk(db, org_id, module_name, values):
        captured.setdefault(module_name, {}).update(values)

    from app.core.public_api import core_api

    original_set_bulk = core_api.settings.set_bulk_async
    core_api.settings.set_bulk_async = fake_set_bulk  # type: ignore[method-assign]
    try:
        db = MagicMock()
        db.run_sync = AsyncMock(side_effect=lambda fn: fn(MagicMock()))
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        # The write journals what it moved (asserted end-to-end in
        # tests/integration/test_onboarding_profile.py); here the entry only
        # has to reach a session that can take it.
        db.flush = AsyncMock()

        org = _make_org()
        await onboarding_service.apply_onboarding_profile_async(
            db, org, 'test', profile=profile
        )
        assert captured == {'webhooks': {'threshold': 5}}
    finally:
        core_api.settings.set_bulk_async = original_set_bulk  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_invalid_module_config_is_skipped_not_fatal(
    patched_org_service,
    restored_module_registry,
) -> None:
    from app.core.exceptions import ValidationException
    from app.core.module_registry import module_registry
    from app.core.product_profiles import ProductProfile
    from app.services import onboarding_service

    module_registry.get = lambda n: _StubModule(  # type: ignore[method-assign,return-value,assignment]
        n,
        {
            'type': 'object',
            'properties': {'threshold': {'type': 'integer', 'minimum': 1}},
        },
    )

    profile = ProductProfile(
        id='test',
        name='Test',
        description='desc',
        default_modules=['webhooks'],
        seed_profile='clean_core',
        module_config={
            'webhooks': {'threshold': 999},
        },
    )

    async def failing_set_bulk(db, org_id, module_name, values):
        raise ValidationException(message='threshold must be <= 100')

    from app.core.public_api import core_api

    original_set_bulk = core_api.settings.set_bulk_async
    core_api.settings.set_bulk_async = failing_set_bulk  # type: ignore[method-assign]
    try:
        db = MagicMock()
        db.run_sync = AsyncMock(side_effect=lambda fn: fn(MagicMock()))
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        org = _make_org()
        result = await onboarding_service.apply_onboarding_profile_async(
            db, org, 'test', profile=profile
        )
        assert result is not None
        assert 'webhooks' in result.enabled_modules
    finally:
        core_api.settings.set_bulk_async = original_set_bulk  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_module_without_schema_skips_config_gracefully(
    patched_org_service,
    restored_module_registry,
) -> None:
    from app.core.module_registry import module_registry
    from app.core.product_profiles import ProductProfile
    from app.services import onboarding_service

    module_registry.get = lambda n: _StubModule(n, None)  # type: ignore[method-assign,return-value,assignment]

    profile = ProductProfile(
        id='test',
        name='Test',
        description='desc',
        default_modules=['legacy'],
        seed_profile='clean_core',
        module_config={'legacy': {'anything': 'goes'}},
    )

    async def should_not_be_called(db, org_id, module_name, values):
        raise AssertionError('should not persist for schema-less module')

    from app.core.public_api import core_api

    original_set_bulk = core_api.settings.set_bulk_async
    core_api.settings.set_bulk_async = should_not_be_called  # type: ignore[method-assign]
    try:
        db = MagicMock()
        db.run_sync = AsyncMock(side_effect=lambda fn: fn(MagicMock()))
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        org = _make_org()
        await onboarding_service.apply_onboarding_profile_async(
            db, org, 'test', profile=profile
        )
    finally:
        core_api.settings.set_bulk_async = original_set_bulk  # type: ignore[method-assign]
