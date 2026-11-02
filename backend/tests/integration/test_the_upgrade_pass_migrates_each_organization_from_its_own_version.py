"""The upgrade pass rewrites every organization's settings from its own version.

``on_upgrade`` runs once per installation, but the data it exists for lives
per organization: each one saved its settings blob against whatever shape the
module declared at the time. A module that renames a setting needs a
per-organization pass that reads each blob's stamped schema version and
rewrites it from there — two organizations on different versions are two
different migrations, not one.

The pass lives on the upgrade context (``context.migrate_settings``) so a
module's ``on_upgrade_async`` can drive it, and it stamps every blob it
touches with the version it migrated to, so the next shape change knows what
it is reading.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.context import ModuleContext
from app.core.module_registry import module_registry
from app.models.module_installation import ModuleInstallation
from app.models.organization import Organization

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _RenamingModule(BaseModule):
    """A module whose second shape renames ``timeout_s`` to ``timeout``."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.seen: list[tuple[uuid.UUID, int]] = []

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            version='2.0.0',
            display_name='Renaming',
            description='Renames a setting across organizations',
            icon='Box',
        )

    def register_routes(self) -> APIRouter:
        return APIRouter()

    def get_settings_schema(self) -> dict:
        return {
            'type': 'object',
            'version': 2,
            'properties': {'timeout': {'type': 'integer'}},
        }

    async def on_upgrade_async(self, old_version: str, context: ModuleContext) -> None:
        name = self.metadata.name

        def rename(org_id: uuid.UUID, from_version: int, settings: dict) -> dict:
            self.seen.append((org_id, from_version))
            return {'timeout': settings.get('timeout_s', settings.get('timeout'))}

        self.migrated = await context.migrate_settings(name, rename)


@pytest.fixture
def module() -> _RenamingModule:
    return _RenamingModule(f'settingspass_{uuid.uuid4().hex[:8]}')


@pytest.fixture
def _stub_registry_get():
    """The pass resolves the declared version through the registry."""

    original_get = module_registry.get
    yield
    module_registry.get = original_get  # type: ignore[method-assign]


class TestTwoOrganizationsOnDifferentVersions:
    async def test_each_is_migrated_from_its_own_version(
        self,
        module: _RenamingModule,
        real_async_db_session: AsyncSession,
        _stub_registry_get,
    ) -> None:
        name = module.metadata.name
        namespace = f'module:{name}'

        # Saved before any stamping existed — reads as version 0.
        org_a = Organization(name='Org A', settings={namespace: {'timeout_s': 5}})
        # Saved against shape 1.
        org_b = Organization(
            name='Org B',
            settings={namespace: {'timeout_s': 7, '__schema_version': 1}},
        )
        real_async_db_session.add_all([org_a, org_b])
        real_async_db_session.add(
            ModuleInstallation(module_name=name, installed_version='1.0.0')
        )
        await real_async_db_session.flush()

        module_registry.get = (  # type: ignore[method-assign]
            lambda n, _module=module: _module if n == name else None
        )
        await module_registry.check_module_version_async(module, real_async_db_session)
        await real_async_db_session.flush()

        # Each organization was read at its own stored version.
        assert set(module.seen) == {(org_a.id, 0), (org_b.id, 1)}
        assert module.migrated == 2

        rewritten = await real_async_db_session.scalar(
            select(Organization).where(Organization.id == org_a.id)
        )
        assert rewritten is not None
        assert rewritten.settings[namespace] == {
            'timeout': 5,
            '__schema_version': 2,
        }
        rewritten = await real_async_db_session.scalar(
            select(Organization).where(Organization.id == org_b.id)
        )
        assert rewritten is not None
        assert rewritten.settings[namespace] == {
            'timeout': 7,
            '__schema_version': 2,
        }
