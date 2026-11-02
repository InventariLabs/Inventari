"""Contract DTO tests for CoreStorageTypesAPI.

Pins the ``app.core.contracts`` input DTOs (``StorageTypeCreateDTO`` /
``StorageTypeUpdateDTO``) and the ``lang: str | None`` primitive — the types
community modules program against.
"""

from __future__ import annotations

import pytest

from app.core.contracts import (
    StorageTypeCreateDTO,
    StorageTypeDTO,
    StorageTypeUpdateDTO,
)
from app.core.exceptions import ContractViolationError
from app.core.public_api import core_api

from ._core_api_helpers import make_user_context


@pytest.mark.integration
class TestCoreStorageTypesCreateDto:
    """``create_async`` accepts StorageTypeCreateDTO and returns StorageTypeDTO."""

    @pytest.mark.asyncio
    async def test_create_via_dto_success(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = StorageTypeCreateDTO(
            name='Custom Shelf',
            type_code='CUSTOM_SHELF',
            icon='shelf',
        )

        result = await core_api.location_types.create_async(
            real_async_db_session, data, user_ctx, lang='en'
        )

        assert isinstance(result, StorageTypeDTO)
        assert result.name == 'Custom Shelf'
        assert result.type_code == 'CUSTOM_SHELF'
        assert result.organization_id == async_test_household.id

    @pytest.mark.asyncio
    async def test_create_via_dto_lang_de(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """lang='de' is accepted (not the app.i18n.Language type anymore)."""
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = StorageTypeCreateDTO(
            name='Regal',
            type_code='REGAL_DE',
        )

        result = await core_api.location_types.create_async(
            real_async_db_session, data, user_ctx, lang='de'
        )

        assert isinstance(result, StorageTypeDTO)
        assert result.name == 'Regal'

    @pytest.mark.asyncio
    async def test_create_dto_duplicate_raises(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = StorageTypeCreateDTO(name='Dup', type_code='DUP_ST')

        await core_api.location_types.create_async(
            real_async_db_session, data, user_ctx, lang='en'
        )

        with pytest.raises(ValueError):
            await core_api.location_types.create_async(
                real_async_db_session, data, user_ctx, lang='en'
            )

    @pytest.mark.asyncio
    async def test_create_dto_lang_none_ok(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """lang=None is accepted (default)."""
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = StorageTypeCreateDTO(name='No Lang', type_code='NO_LANG')

        result = await core_api.location_types.create_async(
            real_async_db_session, data, user_ctx
        )

        assert isinstance(result, StorageTypeDTO)


@pytest.mark.integration
class TestCoreStorageTypesLangValidation:
    """``lang`` is validated against the supported set."""

    @pytest.mark.asyncio
    async def test_create_invalid_lang_raises(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = StorageTypeCreateDTO(name='X', type_code='LANG_BAD')

        with pytest.raises(ContractViolationError, match='Unsupported language code'):
            await core_api.location_types.create_async(
                real_async_db_session, data, user_ctx, lang='xx'
            )

    @pytest.mark.asyncio
    async def test_update_invalid_lang_raises(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        # Create a valid type first
        create_data = StorageTypeCreateDTO(name='Valid', type_code='VALID_LANG_UP')
        created = await core_api.location_types.create_async(
            real_async_db_session, create_data, user_ctx, lang='en'
        )

        update_data = StorageTypeUpdateDTO(name='Updated')
        with pytest.raises(ContractViolationError, match='Unsupported language code'):
            await core_api.location_types.update_async(
                real_async_db_session, created.id, update_data, user_ctx, lang='xx'
            )


@pytest.mark.integration
class TestCoreStorageTypesUpdateDto:
    """``update_async`` accepts StorageTypeUpdateDTO with PATCH semantics."""

    @pytest.mark.asyncio
    async def test_update_via_dto_partial(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        create_data = StorageTypeCreateDTO(name='Original', type_code='UP_PARTIAL')
        created = await core_api.location_types.create_async(
            real_async_db_session, create_data, user_ctx, lang='en'
        )

        update_data = StorageTypeUpdateDTO(name='Renamed')

        result = await core_api.location_types.update_async(
            real_async_db_session, created.id, update_data, user_ctx, lang='en'
        )

        assert isinstance(result, StorageTypeDTO)
        assert result.name == 'Renamed'
        assert result.type_code == 'UP_PARTIAL'  # unchanged

    @pytest.mark.asyncio
    async def test_update_not_found_returns_none(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        import uuid

        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        update_data = StorageTypeUpdateDTO(name='Ghost')

        result = await core_api.location_types.update_async(
            real_async_db_session, uuid.uuid4(), update_data, user_ctx, lang='en'
        )

        assert result is None
