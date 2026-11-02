"""
Contract tests for CoreItemsAPI (app.core.public_api.core_api.items).

These tests pin down the SHAPE of every public method (async
variants) and assert the multi-tenant org-scoping contract: an item
belonging to one organization must never be visible to another.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.contracts import ItemCreateDTO
from app.core.public_api import core_api
from app.models.item import Item

from ._core_api_helpers import (
    make_other_org,
    make_user_context,
    run_async,
)


@pytest.mark.integration
class TestCoreItemsGetContract:
    """`get_async` return ItemDTO or None; org-scoped."""

    def test_get_async_returns_dto(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.get_async(
                    session, test_household.id, test_item.id
                )

        result = run_async(_fetch())
        assert result is not None
        assert result.id == test_item.id
        assert result.name == test_item.name

    def test_get_async_returns_none_for_missing(
        self, db_session, test_household, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.get_async(
                    session, test_household.id, uuid4()
                )

        result = run_async(_fetch())
        assert result is None

    def test_get_async_is_org_scoped(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        other_org = make_other_org(db_session)

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.get_async(
                    session, other_org.id, test_item.id
                )

        result = run_async(_fetch())
        assert result is None


@pytest.mark.integration
class TestCoreItemsListContract:
    """`list_async` return list[ItemDTO] with filters applied."""

    def test_list_async_returns_list_of_dtos(
        self,
        db_session,
        test_household,
        test_item,
        test_items_batch,
        async_engine_fixture,
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.list_async(
                    session, test_household.id, limit=50
                )

        result = run_async(_fetch())
        assert isinstance(result, list)
        assert len(result) >= 1
        for item in result:
            assert item.organization_id == test_household.id

    def test_list_async_filters_by_storage_location(
        self,
        db_session,
        test_household,
        test_item,
        test_storage_location,
        async_engine_fixture,
    ):
        from app.database import async_sessionmaker

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.list_async(
                    session,
                    test_household.id,
                    storage_location_id=test_storage_location.id,
                )

        result = run_async(_fetch())
        assert all(item.location_id == test_storage_location.id for item in result)

    def test_list_async_excludes_other_org_items(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        other_org = make_other_org(db_session)

        async def _fetch():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.list_async(session, other_org.id, limit=50)

        result = run_async(_fetch())
        assert all(item.organization_id != test_household.id for item in result)


@pytest.mark.integration
class TestCoreItemsCountContract:
    """`count_async` return int, filterable by is_deleted."""

    def test_count_async_returns_int(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _count():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.count_async(session, test_household.id)

        result = run_async(_count())
        assert isinstance(result, int)
        assert result >= 1

    def test_count_async_excludes_other_org(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        other_org = make_other_org(db_session)

        async def _count():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.count_async(session, other_org.id)

        result = run_async(_count())
        assert result == 0

    def test_count_async_filters_deleted(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        test_item.is_deleted = True
        db_session.commit()

        async def _count():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                active = await core_api.items.count_async(
                    session, test_household.id, is_deleted=False
                )
                deleted = await core_api.items.count_async(
                    session, test_household.id, is_deleted=True
                )
                return active, deleted

        active, deleted = run_async(_count())
        assert active + deleted >= 1


@pytest.mark.integration
class TestCoreItemsBarcodeContract:
    """`has_active_barcode_async` returns bool, org-scoped."""

    def test_has_active_barcode_async_true_for_existing(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        test_item.barcode = 'TEST-12345'
        db_session.commit()

        async def _check():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.has_active_barcode_async(
                    session, test_household.id, 'TEST-12345'
                )

        assert run_async(_check()) is True

    def test_has_active_barcode_async_false_for_missing(
        self, db_session, test_household, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        async def _check():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.has_active_barcode_async(
                    session, test_household.id, 'NO-SUCH-BARCODE'
                )

        assert run_async(_check()) is False

    def test_has_active_barcode_async_is_org_scoped(
        self, db_session, test_household, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        other_org = make_other_org(db_session)
        test_item.barcode = 'ORG-12345'
        db_session.commit()

        async def _check():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                return await core_api.items.has_active_barcode_async(
                    session, other_org.id, 'ORG-12345'
                )

        assert run_async(_check()) is False


@pytest.mark.integration
class TestCoreItemsCreateContract:
    """`create` returns ItemDTO, runs interceptor pipeline."""

    @pytest.mark.asyncio
    async def test_create_returns_dto(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        from app.core.public_api import core_api

        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        item_in = ItemCreateDTO(
            name='Contract Test Item',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1.0'),
        )

        result = await core_api.items.create_async(
            real_async_db_session, async_test_household.id, item_in, user_ctx
        )

        assert result is not None
        assert result.name == 'Contract Test Item'
        assert result.organization_id == async_test_household.id

        # Verify DB has the item
        from sqlalchemy import select

        item = (
            await real_async_db_session.scalars(
                select(Item).where(Item.id == result.id)
            )
        ).first()
        assert item is not None
        assert item.organization_id == async_test_household.id

    @pytest.mark.asyncio
    async def test_create_refuses_an_organization_the_user_does_not_write_in(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """The facade takes `organization_id`; the service writes into the
        user's. When the two differ, the call says so instead of choosing one
        in silence and filing the record where the caller did not ask."""
        from sqlalchemy import select

        from app.core.exceptions import ContractViolationError
        from app.core.public_api import core_api
        from app.models.organization import Organization

        other = Organization(name='Other Org', enabled_modules=['core'])
        real_async_db_session.add(other)
        await real_async_db_session.commit()

        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        item_in = ItemCreateDTO(
            name='Filed Elsewhere',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1.0'),
        )

        with pytest.raises(ContractViolationError):
            await core_api.items.create_async(
                real_async_db_session, other.id, item_in, user_ctx
            )

        await real_async_db_session.rollback()
        created = (
            await real_async_db_session.scalars(
                select(Item).where(Item.name == 'Filed Elsewhere')
            )
        ).all()
        assert created == []


@pytest.mark.integration
class TestCoreItemsUpdateQuantityContract:
    """`update_quantity` mutates Item.quantity, which is what the shelf reads."""

    def test_update_quantity_changes_value(
        self, db_session, test_household, test_user, test_item, async_engine_fixture
    ):
        from app.database import async_sessionmaker

        original = test_item.quantity

        async def _update():
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )
            async with maker() as session:
                result = await core_api.items.update_quantity_async(
                    session,
                    test_household.id,
                    test_item.id,
                    quantity=Decimal('42.0'),
                    user_id=test_user.id,
                )
                await session.commit()
                return result

        result = run_async(_update())
        assert result is not None
        assert result.quantity == Decimal('42.0')

        # DB reflects change
        db_session.refresh(test_item)
        assert test_item.quantity == Decimal('42.0')
        assert test_item.quantity != original
