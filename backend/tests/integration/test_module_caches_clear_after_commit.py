"""The module caches are cleared once the new set is committed, from every writer.

Cleared before the commit, a read in the gap re-caches the old committed set
for the full TTL. And a CLI process never ran the app lifespan, so the cache
client is unset there and a plain delete does nothing at all.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy import select

from app.core import cache as cache_module
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token
from tests.integration._fake_redis import FakeRedis

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _admin(db) -> User:
    org = Organization(
        name='Cache Order Org', enabled_modules=['core', 'items', 'locations']
    )
    db.add(org)
    await db.flush()
    user = User(
        email=f'cacheorder_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Cache Order Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_toggle_clears_the_caches_after_the_commit(
    real_async_client, real_async_db_session, monkeypatch
):
    """Guard: the toggle service commits itself, and the route must keep
    clearing only after that. Passes with or without a route-level commit."""
    user = await _admin(real_async_db_session)
    org_id = user.organization_id
    seen: list[bool] = []

    async def _probe(*keys):
        async with real_async_db_session.bind.connect() as conn:
            modules = await conn.scalar(
                select(Organization.enabled_modules).where(Organization.id == org_id)
            )
        seen.append('vision' in (modules or []))

    monkeypatch.setattr('app.core._require_module.cache_delete', _probe)

    response = await real_async_client.post(
        '/api/v1/modules/toggle',
        headers={
            'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
        },
        json={'module_name': 'vision', 'enabled': True},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert seen == [True]


async def test_a_cli_process_can_clear_the_caches(monkeypatch):
    """With no injected client, the standalone delete reaches Redis anyway."""
    from app.core._require_module import invalidate_org_module_caches

    fake = FakeRedis()
    await fake.set('org:o1:modules', '[]')
    await fake.set('org:o1:modules:enabled', '[]')
    fake.aclose = _noop  # type: ignore[attr-defined]
    monkeypatch.setattr(cache_module, '_redis', None)
    monkeypatch.setattr('redis.asyncio.Redis.from_url', lambda *a, **k: fake)

    await invalidate_org_module_caches('o1', standalone=True)

    assert await fake.get('org:o1:modules') is None
    assert await fake.get('org:o1:modules:enabled') is None


async def _noop() -> None:
    return None
