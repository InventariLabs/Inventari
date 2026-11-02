"""
Tests for the recipes module settings after the reader key moved to the
AI Connections registry.

Since 2026-09-28 a credential for an external provider
lives where the administrator rotates and tests it — /settings/ai — not on
the screen a cook opens. So the recipes schema carries no reader key (and
nothing that asks about rate limits), the settings door refuses one, and
the startup migrator moves whatever an older install stored in either
legacy home into a registry connection bound to ``recipes.url_fetch``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_connection import AiConnection
from app.models.organization import Organization
from app.modules.recipes.module import RecipesModule


@pytest.mark.integration
def test_recipes_schema_carries_no_reader_key() -> None:
    """The settings a cook sees must not ask what a reader or a rate
    limit is — the whole field is gone, not reworded."""
    schema = RecipesModule().get_settings_schema()
    assert schema is not None
    assert 'jina' not in schema['properties']
    rendered = repr(schema)
    assert 'jina' not in rendered.lower()
    assert 'RPM' not in rendered


@pytest.mark.integration
def test_the_settings_door_refuses_a_reader_key(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """The old write path closes loudly: a payload naming the removed
    field is a 422 naming it, not a silent store nobody reads."""
    response = client.put(
        '/api/v1/modules/recipes/settings',
        json={'jina': {'api_key': 'jina-round-trip'}},
        headers=auth_headers,
    )
    assert response.status_code in (400, 422), response.text
    assert 'jina' in response.text


async def _org_with_settings(
    db: AsyncSession, settings: dict[str, Any]
) -> Organization:
    org = Organization(
        name=f'Mig {uuid4().hex[:6]}', enabled_modules=['core', 'items', 'recipes']
    )
    org.settings = settings
    db.add(org)
    await db.flush()
    return org


@pytest.mark.asyncio
@pytest.mark.integration
class TestTheReaderKeyMigration:
    async def test_the_namespaced_key_becomes_a_bound_connection(
        self, real_async_db_session: AsyncSession
    ) -> None:
        from app.services.crypto_service import encrypt_module_secret

        org = await _org_with_settings(
            real_async_db_session,
            {
                'module:recipes': {
                    'jina': {'api_key': encrypt_module_secret('recipes', 'mig-key')}
                }
            },
        )

        from app.modules.recipes.migration import (
            migrate_all_orgs_recipes_jina_key_async,
        )

        migrated = await migrate_all_orgs_recipes_jina_key_async(real_async_db_session)

        assert migrated == 1
        await real_async_db_session.refresh(org)
        assert 'jina' not in (org.settings or {}).get('module:recipes', {})
        rows = list(
            await real_async_db_session.scalars(
                select(AiConnection).where(AiConnection.organization_id == org.id)
            )
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.provider == 'jina'
        assert row.capabilities == ['url_fetch']
        assert row.api_key_enc.startswith('enc:')
        assert 'mig-key' not in row.api_key_enc
        assert (org.settings or {})['ai']['defaults']['recipes.url_fetch'] == str(
            row.id
        )

    async def test_the_legacy_plaintext_key_moves_and_never_lands_plaintext(
        self, real_async_db_session: AsyncSession
    ) -> None:
        org = await _org_with_settings(
            real_async_db_session,
            {'modules': {'recipes': {'jina': {'api_key': 'legacy-plain'}}}},
        )

        from app.modules.recipes.migration import (
            migrate_all_orgs_recipes_jina_key_async,
        )

        migrated = await migrate_all_orgs_recipes_jina_key_async(real_async_db_session)

        assert migrated == 1
        await real_async_db_session.refresh(org)
        assert 'jina' not in (org.settings or {}).get('modules', {}).get('recipes', {})
        row = (
            await real_async_db_session.scalars(
                select(AiConnection).where(AiConnection.organization_id == org.id)
            )
        ).one()
        assert row.api_key_enc != 'legacy-plain'
        assert row.api_key_enc.startswith('enc:')

    async def test_an_existing_reader_connection_is_bound_not_duplicated(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """An org that already set the registry up by hand keeps its row —
        the migrator binds it instead of creating a second one."""
        org = await _org_with_settings(
            real_async_db_session,
            {'modules': {'recipes': {'jina': {'api_key': 'late-key'}}}},
        )
        existing = AiConnection(
            organization_id=org.id,
            name='Own reader',
            provider='jina',
            capabilities=['url_fetch'],
            api_key_enc='enc:something',
        )
        real_async_db_session.add(existing)
        await real_async_db_session.flush()

        from app.modules.recipes.migration import (
            migrate_all_orgs_recipes_jina_key_async,
        )

        await migrate_all_orgs_recipes_jina_key_async(real_async_db_session)

        await real_async_db_session.refresh(org)
        rows = (
            await real_async_db_session.scalars(
                select(AiConnection).where(AiConnection.organization_id == org.id)
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].id == existing.id
        assert (org.settings or {})['ai']['defaults']['recipes.url_fetch'] == str(
            existing.id
        )

    async def test_the_namespaced_value_wins_but_the_stale_copy_still_goes(
        self, real_async_db_session: AsyncSession
    ) -> None:
        from app.services.crypto_service import encrypt_module_secret

        org = await _org_with_settings(
            real_async_db_session,
            {
                'modules': {'recipes': {'jina': {'api_key': 'stale'}}},
                'module:recipes': {
                    'jina': {'api_key': encrypt_module_secret('recipes', 'current')}
                },
            },
        )

        from app.modules.recipes.migration import (
            migrate_all_orgs_recipes_jina_key_async,
        )

        await migrate_all_orgs_recipes_jina_key_async(real_async_db_session)

        await real_async_db_session.refresh(org)
        settings = org.settings or {}
        assert 'jina' not in settings.get('modules', {}).get('recipes', {})
        assert 'jina' not in settings.get('module:recipes', {})
        from app.core.llm.secrets import decrypt_connection_secret

        row = (
            await real_async_db_session.scalars(
                select(AiConnection).where(AiConnection.organization_id == org.id)
            )
        ).one()
        assert decrypt_connection_secret(row.api_key_enc) == 'current'

    async def test_nothing_to_migrate_touches_nothing(
        self, real_async_db_session: AsyncSession
    ) -> None:
        org = await _org_with_settings(real_async_db_session, {'ai': {'defaults': {}}})

        from app.modules.recipes.migration import (
            migrate_all_orgs_recipes_jina_key_async,
        )

        migrated = await migrate_all_orgs_recipes_jina_key_async(real_async_db_session)

        assert migrated == 0
        await real_async_db_session.refresh(org)
        assert org.settings == {'ai': {'defaults': {}}}

    async def test_the_sweep_is_idempotent(
        self, real_async_db_session: AsyncSession
    ) -> None:
        org = await _org_with_settings(
            real_async_db_session,
            {'modules': {'recipes': {'jina': {'api_key': 'once'}}}},
        )

        from app.modules.recipes.migration import (
            migrate_all_orgs_recipes_jina_key_async,
        )

        assert await migrate_all_orgs_recipes_jina_key_async(real_async_db_session) == 1
        assert await migrate_all_orgs_recipes_jina_key_async(real_async_db_session) == 0
        rows = (
            await real_async_db_session.scalars(
                select(AiConnection).where(AiConnection.organization_id == org.id)
            )
        ).all()
        assert len(rows) == 1
