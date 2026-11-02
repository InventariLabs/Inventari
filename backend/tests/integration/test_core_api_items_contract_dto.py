"""Contract DTO tests for CoreItemsAPI.

Pins the ``app.core.contracts`` input DTOs (``ItemCreateDTO`` /
``ItemUpdateDTO``) and the ``CursorPaginatedDTO`` return alias — the types
community modules program against.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.contracts import (
    CursorPaginatedDTO,
    ItemCreateDTO,
    ItemDTO,
    ItemUpdateDTO,
)
from app.core.public_api import core_api
from app.models.organization import Organization
from app.schemas.pagination import CursorPaginatedResponse

from ._core_api_helpers import make_user_context


@pytest.mark.integration
class TestCoreItemsCreateDto:
    """`create` accepts ItemCreateDTO and returns ItemDTO."""

    @pytest.mark.asyncio
    async def test_create_via_dto_success(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = ItemCreateDTO(
            name='DTO Item',
            location_id=async_test_storage_location.id,
            quantity=Decimal('2'),
            brand='Acme',
        )

        result = await core_api.items.create_async(
            real_async_db_session, async_test_household.id, data, user_ctx
        )

        assert isinstance(result, ItemDTO)
        assert result.name == 'DTO Item'
        assert result.organization_id == async_test_household.id
        assert result.quantity == Decimal('2')

    @pytest.mark.asyncio
    async def test_create_dto_with_template_id_binds_that_card(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """A card named in the DTO binds the record; no name matching runs."""
        from app.models.product_template import ProductTemplate

        first = ProductTemplate(
            organization_id=async_test_household.id, name='DTO Twin'
        )
        second = ProductTemplate(
            organization_id=async_test_household.id, name='DTO Twin'
        )
        real_async_db_session.add_all([first, second])
        await real_async_db_session.flush()

        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = ItemCreateDTO(
            name='DTO Twin',
            location_id=async_test_storage_location.id,
            quantity=Decimal('1'),
            template_id=second.id,
        )

        result = await core_api.items.create_async(
            real_async_db_session, async_test_household.id, data, user_ctx
        )

        assert result.template_id == second.id

    @pytest.mark.asyncio
    async def test_create_dto_quantity_float_normalized(
        self, async_test_storage_location
    ):
        """Float quantities convert via str — no binary float artifacts."""
        data = ItemCreateDTO(
            name='Float Qty',
            location_id=async_test_storage_location.id,
            quantity=0.1,
        )
        assert data.quantity == Decimal('0.1')

    def test_create_dto_negative_quantity_rejected(self, async_test_storage_location):
        with pytest.raises(ValidationError):
            ItemCreateDTO(
                name='Negative',
                location_id=async_test_storage_location.id,
                quantity=Decimal('-1'),
            )

    @pytest.mark.asyncio
    async def test_create_dto_empty_strings_normalized(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """Empty strings flow through the internal schema and land as NULL."""
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        data = ItemCreateDTO(
            name='Empty Strings',
            location_id=async_test_storage_location.id,
            brand='',
        )

        result = await core_api.items.create_async(
            real_async_db_session, async_test_household.id, data, user_ctx
        )

        assert result.brand is None


@pytest.mark.integration
class TestCoreItemsUpdateDto:
    """`update` accepts ItemUpdateDTO with PATCH semantics."""

    @pytest.mark.asyncio
    async def test_update_via_dto_partial(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        created = await core_api.items.create_async(
            real_async_db_session,
            async_test_household.id,
            ItemCreateDTO(
                name='Before',
                location_id=async_test_storage_location.id,
                brand='Keep',
            ),
            user_ctx,
        )

        result = await core_api.items.update_async(
            real_async_db_session,
            async_test_household.id,
            created.id,
            ItemUpdateDTO(name='After'),
            user_ctx,
        )

        assert result is not None
        assert result.name == 'After'
        # PATCH semantics: unset fields are untouched.
        assert result.brand == 'Keep'

    @pytest.mark.asyncio
    async def test_update_missing_item_returns_none(
        self, real_async_db_session, async_test_household, async_test_user
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)

        result = await core_api.items.update_async(
            real_async_db_session,
            async_test_household.id,
            uuid4(),
            ItemUpdateDTO(name='Ghost'),
            user_ctx,
        )

        assert result is None


@pytest.mark.integration
class TestCoreItemsDtoOrgIsolation:
    """DTO-based calls stay org-scoped."""

    @pytest.mark.asyncio
    async def test_update_other_org_item_returns_none(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        created = await core_api.items.create_async(
            real_async_db_session,
            async_test_household.id,
            ItemCreateDTO(
                name='Org A Item',
                location_id=async_test_storage_location.id,
            ),
            user_ctx,
        )
        other = Organization(name='Other Org', enabled_modules=['core'])
        real_async_db_session.add(other)
        await real_async_db_session.flush()

        result = await core_api.items.update_async(
            real_async_db_session,
            other.id,
            created.id,
            ItemUpdateDTO(name='Hijacked'),
            user_ctx,
        )

        assert result is None
        untouched = await core_api.items.get_async(
            real_async_db_session, async_test_household.id, created.id
        )
        assert untouched is not None
        assert untouched.name == 'Org A Item'

    @pytest.mark.asyncio
    async def test_search_scoped_to_org(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        await core_api.items.create_async(
            real_async_db_session,
            async_test_household.id,
            ItemCreateDTO(
                name='Scoped Item',
                location_id=async_test_storage_location.id,
            ),
            user_ctx,
        )
        other = Organization(name='Other Org', enabled_modules=['core'])
        real_async_db_session.add(other)
        await real_async_db_session.flush()

        result = await core_api.items.search_cursor_paginated_async(
            real_async_db_session, other.id
        )

        assert result.items == []


@pytest.mark.integration
class TestCursorPaginatedDto:
    """`search_cursor_paginated_async` returns the contracts pagination type."""

    def test_alias_is_canonical_class(self):
        """CursorPaginatedDTO is an alias — zero drift with the envelope."""
        assert CursorPaginatedDTO is CursorPaginatedResponse

    @pytest.mark.asyncio
    async def test_search_returns_contracts_type(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        user_ctx = make_user_context(async_test_household.id, async_test_user.id)
        for i in range(2):
            await core_api.items.create_async(
                real_async_db_session,
                async_test_household.id,
                ItemCreateDTO(
                    name=f'Paged {i}',
                    location_id=async_test_storage_location.id,
                ),
                user_ctx,
            )

        result = await core_api.items.search_cursor_paginated_async(
            real_async_db_session, async_test_household.id, limit=1
        )

        assert isinstance(result, CursorPaginatedResponse)
        assert result.has_more is True
        assert result.next_cursor is not None
        assert len(result.items) == 1
        assert isinstance(result.items[0], ItemDTO)


class TestQuantityColumnCeilingDto:
    """The contract DTOs mirror the column's shape: quantity is capped at
    the largest value a numeric(12, 3) column stores."""

    def test_create_dto_refuses_a_quantity_past_the_ceiling(self):
        with pytest.raises(ValidationError):
            ItemCreateDTO(
                name='Past the ceiling',
                location_id=uuid4(),
                quantity=Decimal('1000000000'),
            )

    def test_update_dto_refuses_a_quantity_past_the_ceiling(self):
        with pytest.raises(ValidationError):
            ItemUpdateDTO(quantity=Decimal('1000000000'))

    def test_the_largest_storable_value_is_accepted(self, async_test_storage_location):
        dto = ItemCreateDTO(
            name='Exactly the ceiling',
            location_id=async_test_storage_location.id,
            quantity=Decimal('999999999.999'),
        )

        assert dto.quantity == Decimal('999999999.999')
