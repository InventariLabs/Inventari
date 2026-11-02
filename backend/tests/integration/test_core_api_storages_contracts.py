"""
Contract tests for CoreStoragesAPI (app.core.public_api.core_api.locations).

These tests pin down the SHAPE of every public method (async
variants) and assert the multi-tenant org-scoping contract: a storage
location belonging to one organization must never be visible to another.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.public_api import core_api

from ._core_api_helpers import make_other_org, run_async


@pytest.mark.integration
class TestCoreStoragesGetContract:
    """`get_async` return StorageDTO or None; org-scoped."""

    def test_get_async_returns_dto_for_existing(
        self, db_session, test_household, test_storage_location, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.locations.get_async(
                    session, test_household.id, test_storage_location.id
                )

        result = run_async(_fetch())
        assert result is not None
        assert result.id == test_storage_location.id
        assert result.name == test_storage_location.name

    def test_get_async_returns_none_for_missing_id(
        self, db_session, test_household, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.locations.get_async(
                    session, test_household.id, uuid4()
                )

        result = run_async(_fetch())
        assert result is None

    def test_get_async_returns_none_for_none_org(
        self, db_session, test_storage_location, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.locations.get_async(
                    session, None, test_storage_location.id
                )

        result = run_async(_fetch())
        assert result is None

    def test_get_async_is_org_scoped(
        self, db_session, test_storage_location, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        other_org = make_other_org(db_session)

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.locations.get_async(
                    session, other_org.id, test_storage_location.id
                )

        result = run_async(_fetch())
        assert result is None


@pytest.mark.integration
class TestCoreStoragesListContract:
    """`list_async` return list[StorageDTO] filtered by org."""

    def test_list_async_returns_list_of_dtos(
        self, db_session, test_household, test_storage_location, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.locations.list_async(session, test_household.id)

        result = run_async(_fetch())
        assert isinstance(result, list)
        assert len(result) >= 1
        for storage in result:
            assert storage.organization_id == test_household.id

    def test_list_async_excludes_other_org(
        self, db_session, test_household, test_storage_location, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        other_org = make_other_org(db_session)

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.locations.list_async(session, other_org.id)

        result = run_async(_fetch())
        assert all(storage.organization_id != test_household.id for storage in result)


@pytest.mark.integration
class TestCoreStoragesCreateContract:
    """`create` returns StorageDTO; runs interceptor pipeline."""

    def test_create_returns_dto(
        self,
        db_session,
        test_household,
        test_user,
        test_storage_type,
        async_engine_fixture,
    ):
        from app.database import async_sessionmaker

        async def _create():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.locations.create_async(
                    db=session,
                    organization_id=test_household.id,
                    name='Contract Test Storage',
                    user_id=test_user.id,
                    description='Test storage for contract tests',
                )

        result = run_async(_create())
        assert result is not None
        assert result.name == 'Contract Test Storage'
        assert result.organization_id == test_household.id
