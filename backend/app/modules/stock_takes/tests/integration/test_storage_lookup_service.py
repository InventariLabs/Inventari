"""Integration tests for ``stock_takes.storage_lookup_service``.

The service resolves storage data exclusively through ``core_api.locations``,
so these tests create real ``StorageLocation`` rows and call the functions
directly on ``real_async_db_session`` — no ``TestClient`` worker-thread
coverage loss.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.storage_lookup_service import (
    get_storage_tree,
    storage_exists,
)


@pytest.fixture
async def storage_lookup_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Storage Lookup Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def storage_lookup_user(
    real_async_db_session: AsyncSession, storage_lookup_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        storage_lookup_org,
        email='storage-lookup@example.com',
        role='admin',
    )


async def _location(
    db: AsyncSession,
    org: Organization,
    user: User,
    name: str,
    parent_id: UUID | None = None,
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org.id,
        created_by=user.id,
        name=name,
        parent_id=parent_id,
    )
    db.add(location)
    await db.flush()
    return location


@pytest.mark.integration
class TestStorageExists:
    async def test_org_none_returns_false(
        self, real_async_db_session: AsyncSession
    ) -> None:
        assert await storage_exists(real_async_db_session, None, uuid.uuid4()) is False

    async def test_existing_location_returns_true(
        self,
        real_async_db_session: AsyncSession,
        storage_lookup_org: Organization,
        storage_lookup_user: User,
    ) -> None:
        location = await _location(
            real_async_db_session, storage_lookup_org, storage_lookup_user, 'Shelf A'
        )
        assert (
            await storage_exists(
                real_async_db_session, storage_lookup_org.id, location.id
            )
            is True
        )

    async def test_missing_location_returns_false(
        self,
        real_async_db_session: AsyncSession,
        storage_lookup_org: Organization,
    ) -> None:
        assert (
            await storage_exists(
                real_async_db_session, storage_lookup_org.id, uuid.uuid4()
            )
            is False
        )


@pytest.mark.integration
class TestGetStorageTree:
    async def test_org_none_returns_empty(
        self, real_async_db_session: AsyncSession
    ) -> None:
        assert await get_storage_tree(real_async_db_session, None, uuid.uuid4()) == (
            [],
            [],
            {},
        )

    async def test_missing_location_returns_empty(
        self,
        real_async_db_session: AsyncSession,
        storage_lookup_org: Organization,
        storage_lookup_user: User,
    ) -> None:
        await _location(
            real_async_db_session, storage_lookup_org, storage_lookup_user, 'Site'
        )
        assert await get_storage_tree(
            real_async_db_session, storage_lookup_org.id, uuid.uuid4()
        ) == ([], [], {})

    async def test_returns_descendants_ancestors_and_paths(
        self,
        real_async_db_session: AsyncSession,
        storage_lookup_org: Organization,
        storage_lookup_user: User,
    ) -> None:
        site = await _location(
            real_async_db_session,
            storage_lookup_org,
            storage_lookup_user,
            'Warehouse A',
        )
        zone = await _location(
            real_async_db_session,
            storage_lookup_org,
            storage_lookup_user,
            'Zone A',
            parent_id=site.id,
        )
        rack = await _location(
            real_async_db_session,
            storage_lookup_org,
            storage_lookup_user,
            'Rack 1',
            parent_id=zone.id,
        )
        shelf = await _location(
            real_async_db_session,
            storage_lookup_org,
            storage_lookup_user,
            'Shelf 1',
            parent_id=rack.id,
        )
        sibling = await _location(
            real_async_db_session,
            storage_lookup_org,
            storage_lookup_user,
            'Shelf 2',
            parent_id=rack.id,
        )

        snapshot_ids, family_ids, paths = await get_storage_tree(
            real_async_db_session, storage_lookup_org.id, zone.id
        )

        assert set(snapshot_ids) == {zone.id, rack.id, shelf.id, sibling.id}
        assert set(family_ids) == {site.id, zone.id, rack.id, shelf.id, sibling.id}
        assert paths[zone.id] == 'Warehouse A › Zone A'
        assert paths[rack.id] == 'Warehouse A › Zone A › Rack 1'
        assert paths[shelf.id] == 'Warehouse A › Zone A › Rack 1 › Shelf 1'
        assert paths[sibling.id] == 'Warehouse A › Zone A › Rack 1 › Shelf 2'
