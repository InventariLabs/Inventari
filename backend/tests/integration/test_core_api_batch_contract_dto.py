"""Contract DTO tests for the batch facades.

Pins the ``app.core.contracts`` input DTOs for labels, categories
(+new ``create_async``), and announcements — the types
community modules program against.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.contracts import (
    AnnouncementCreateDTO,
    AnnouncementDTO,
    CategoryCreateDTO,
    CategoryDTO,
    CategoryUpdateDTO,
    LabelCodeItemDTO,
    LabelPoolCreateDTO,
    LabelPoolDTO,
)
from app.core.public_api import core_api

from ._core_api_helpers import make_user_context

# ── Labels ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestCoreLabelsCreateDto:
    """``generate_pool_async`` and ``create_from_codes_async`` via contract DTOs."""

    @pytest.mark.asyncio
    async def test_generate_pool_via_dto(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = LabelPoolCreateDTO(count=3, prefix='TST')

        result = await core_api.labels.generate_pool_async(
            real_async_db_session, data, user_ctx
        )

        assert len(result) == 3
        assert all(isinstance(r, LabelPoolDTO) for r in result)
        assert all(r.short_code.startswith('TST') for r in result)

    @pytest.mark.asyncio
    async def test_create_from_codes_via_dto(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        codes = [
            LabelCodeItemDTO(short_code='CODE-A'),
            LabelCodeItemDTO(short_code='CODE-B'),
        ]

        result = await core_api.labels.create_from_codes_async(
            real_async_db_session, codes, user_ctx
        )

        assert len(result) == 2
        assert all(isinstance(r, LabelPoolDTO) for r in result)
        codes_returned = {r.short_code for r in result}
        assert codes_returned == {'CODE-A', 'CODE-B'}

    @pytest.mark.asyncio
    async def test_create_from_codes_duplicate_raises(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        codes = [LabelCodeItemDTO(short_code='DUP-LBL')]

        await core_api.labels.create_from_codes_async(
            real_async_db_session, codes, user_ctx
        )

        with pytest.raises(ValueError):
            await core_api.labels.create_from_codes_async(
                real_async_db_session, codes, user_ctx
            )


# ── Categories (+create) ───────────────────────────────────────────────


@pytest.mark.integration
class TestCoreCategoriesCreateDto:
    """New ``create_async`` + ``update_async`` via contract DTOs."""

    @pytest.mark.asyncio
    async def test_create_via_dto_success(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = CategoryCreateDTO(name='Test Category', context_tag='equipment')

        result = await core_api.categories.create_async(
            real_async_db_session, data, user_ctx
        )

        assert isinstance(result, CategoryDTO)
        assert result.name == 'Test Category'
        assert result.organization_id == async_test_household.id

    @pytest.mark.asyncio
    async def test_create_dto_duplicate_raises(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = CategoryCreateDTO(name='Dup Cat')

        await core_api.categories.create_async(real_async_db_session, data, user_ctx)

        with pytest.raises(ValueError, match='already exists'):
            await core_api.categories.create_async(
                real_async_db_session, data, user_ctx
            )

    @pytest.mark.asyncio
    async def test_update_via_dto_partial(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        created = await core_api.categories.create_async(
            real_async_db_session,
            CategoryCreateDTO(name='Upd Cat'),
            user_ctx,
        )

        result = await core_api.categories.update_async(
            real_async_db_session,
            async_test_household.id,
            created.id,
            CategoryUpdateDTO(name='Renamed Cat'),
            user_ctx,
        )

        assert isinstance(result, CategoryDTO)
        assert result.name == 'Renamed Cat'

    @pytest.mark.asyncio
    async def test_update_not_found_returns_none(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        import uuid

        user_ctx = make_user_context(async_test_household.id, async_test_user.id)

        result = await core_api.categories.update_async(
            real_async_db_session,
            async_test_household.id,
            uuid.uuid4(),
            CategoryUpdateDTO(name='Ghost'),
            user_ctx,
        )

        assert result is None


# ── Announcements ──────────────────────────────────────────────────────


@pytest.mark.integration
class TestCoreAnnouncementsCreateDto:
    """``create_async`` via contract DTO."""

    @pytest.mark.asyncio
    async def test_create_via_dto_success(
        self,
        real_async_db_session,
        async_test_user,
    ):
        user_ctx = make_user_context(
            async_test_user.organization_id, async_test_user.id
        )
        data = AnnouncementCreateDTO(
            title='Test Announcement',
            content='This is a test.',
            type='info',
            active_until=datetime.now(UTC) + timedelta(days=1),
        )

        result = await core_api.announcements.create_async(
            real_async_db_session, data, user_ctx
        )

        assert isinstance(result, AnnouncementDTO)
        assert result.title == 'Test Announcement'
        assert result.content == 'This is a test.'

    @pytest.mark.asyncio
    async def test_create_dto_invalid_type_raises(self):
        """Invalid announcement type is rejected by the DTO itself."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnnouncementCreateDTO(
                title='Bad Type',
                content='...',
                type='bogus',
            )
