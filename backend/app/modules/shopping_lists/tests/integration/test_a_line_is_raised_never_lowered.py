"""A listed line is topped up when its need grows — and only then.

``raise_item_quantity_async`` keeps a line in step with a need that grew (the
meal plan's refresh, a production run's shortage, recipes added to a list).
Its refusals and no-ops are the contract: the same quantity guard as the add
door, a bought line left alone, a line never lowered.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ShoppingListItemCreateDTO
from app.core.exceptions import ServiceRejectionError
from app.models.user import User
from app.modules.shopping_lists.models import ShoppingListItem
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

from .test_the_facade_quantizes_and_refuses_a_zero import (
    ROUNDS_TO_ZERO,
    _org_of,
    a_list,
)


async def rows_of(db: AsyncSession, list_id: UUID) -> list[ShoppingListItem]:
    """The list's rows as the database holds them, not as the session cached."""
    result = await db.scalars(
        select(ShoppingListItem)
        .where(ShoppingListItem.shopping_list_id == list_id)
        .execution_options(populate_existing=True)
    )
    return list(result)


async def a_line(
    db: AsyncSession,
    user: User,
    quantity: str = '200',
    *,
    source: str = 'meal_plan',
    note: str | None = 'for 200',
) -> ShoppingListItem:
    """A list with one line on it."""
    shopping_list = await a_list(db, user)
    [dto] = await shopping_lists_api.add_items_async(
        db,
        shopping_list.id,
        [
            ShoppingListItemCreateDTO(
                name='Flour',
                quantity=Decimal(quantity),
                source=source,
                notes=note,
                note_data={'for': note},
            )
        ],
        _org_of(user),
    )
    line = await db.get(ShoppingListItem, dto.id)
    assert line is not None
    return line


@pytest.mark.integration
class TestRaiseItemQuantity:
    @pytest.mark.asyncio
    async def test_a_larger_quantity_raises_the_line_and_its_note(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        line = await a_line(real_async_db_session, async_test_user)

        raised = await shopping_lists_api.raise_item_quantity_async(
            real_async_db_session,
            line.shopping_list_id,
            line.id,
            Decimal('500'),
            _org_of(async_test_user),
            notes='for 500',
            note_data={'for': 'for 500'},
        )

        assert raised is True
        await real_async_db_session.refresh(line)
        assert (line.quantity, line.notes, line.note_data) == (
            Decimal('500'),
            'for 500',
            {'for': 'for 500'},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize('quantity', ['200', '150'])
    async def test_a_quantity_at_or_below_the_lines_own_changes_nothing(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        quantity: str,
    ) -> None:
        line = await a_line(real_async_db_session, async_test_user)

        raised = await shopping_lists_api.raise_item_quantity_async(
            real_async_db_session,
            line.shopping_list_id,
            line.id,
            Decimal(quantity),
            _org_of(async_test_user),
            notes='changed',
        )

        assert raised is False
        await real_async_db_session.refresh(line)
        assert (line.quantity, line.notes) == (Decimal('200'), 'for 200')

    @pytest.mark.asyncio
    async def test_a_line_already_ticked_off_is_left_alone(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        line = await a_line(real_async_db_session, async_test_user)
        line.is_purchased = True
        await real_async_db_session.flush()

        raised = await shopping_lists_api.raise_item_quantity_async(
            real_async_db_session,
            line.shopping_list_id,
            line.id,
            Decimal('500'),
            _org_of(async_test_user),
        )

        assert raised is False
        await real_async_db_session.refresh(line)
        assert line.quantity == Decimal('200')

    @pytest.mark.asyncio
    async def test_a_quantity_that_rounds_to_zero_or_overflows_is_refused(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        line = await a_line(real_async_db_session, async_test_user)

        for quantity, key in (
            (ROUNDS_TO_ZERO, 'shopping_list_item_quantity_rounds_to_zero'),
            (Decimal('1000000000.5'), 'shopping_list_item_quantity_above_ceiling'),
        ):
            with pytest.raises(ServiceRejectionError) as refused:
                await shopping_lists_api.raise_item_quantity_async(
                    real_async_db_session,
                    line.shopping_list_id,
                    line.id,
                    quantity,
                    _org_of(async_test_user),
                )
            assert refused.value.key == key

        await real_async_db_session.refresh(line)
        assert line.quantity == Decimal('200')


@pytest.mark.integration
class TestTopUp:
    @pytest.mark.asyncio
    async def test_the_open_line_of_the_same_source_is_raised_to_the_need(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        line = await a_line(real_async_db_session, async_test_user)
        org = _org_of(async_test_user)
        lines = await shopping_lists_api.get_list_items_async(
            real_async_db_session, line.shopping_list_id, org
        )

        written = await shopping_lists_api.top_up_async(
            real_async_db_session,
            line.shopping_list_id,
            ShoppingListItemCreateDTO(
                name='Flour',
                quantity=Decimal('500'),
                source='meal_plan',
                notes='for 500',
            ),
            lines,
            org,
        )

        assert written is not None
        assert written.quantity == Decimal('500')
        rows = await rows_of(real_async_db_session, line.shopping_list_id)
        assert [(r.quantity, r.notes) for r in rows] == [(Decimal('500'), 'for 500')]

    @pytest.mark.asyncio
    async def test_a_need_the_list_already_covers_writes_nothing(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        line = await a_line(real_async_db_session, async_test_user)
        org = _org_of(async_test_user)
        lines = await shopping_lists_api.get_list_items_async(
            real_async_db_session, line.shopping_list_id, org
        )

        written = await shopping_lists_api.top_up_async(
            real_async_db_session,
            line.shopping_list_id,
            ShoppingListItemCreateDTO(
                name='Flour', quantity=Decimal('200'), source='meal_plan'
            ),
            lines,
            org,
        )

        assert written is None
        rows = await rows_of(real_async_db_session, line.shopping_list_id)
        assert [r.quantity for r in rows] == [Decimal('200')]

    @pytest.mark.asyncio
    async def test_a_bought_line_counts_as_cover_and_the_rest_is_a_new_line(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        """Nothing links a bought line to stock, so it counts once as cover."""
        line = await a_line(real_async_db_session, async_test_user)
        line.is_purchased = True
        await real_async_db_session.flush()
        org = _org_of(async_test_user)
        lines = await shopping_lists_api.get_list_items_async(
            real_async_db_session, line.shopping_list_id, org
        )

        written = await shopping_lists_api.top_up_async(
            real_async_db_session,
            line.shopping_list_id,
            ShoppingListItemCreateDTO(
                name='Flour', quantity=Decimal('500'), source='meal_plan'
            ),
            lines,
            org,
        )

        assert written is not None
        assert written.quantity == Decimal('300')
        rows = await rows_of(real_async_db_session, line.shopping_list_id)
        assert sorted((r.is_purchased, r.quantity) for r in rows) == [
            (False, Decimal('300')),
            (True, Decimal('200')),
        ]

    @pytest.mark.asyncio
    async def test_a_line_another_source_wrote_is_not_raised(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        line = await a_line(real_async_db_session, async_test_user, source='manual')
        org = _org_of(async_test_user)
        lines = await shopping_lists_api.get_list_items_async(
            real_async_db_session, line.shopping_list_id, org
        )

        await shopping_lists_api.top_up_async(
            real_async_db_session,
            line.shopping_list_id,
            ShoppingListItemCreateDTO(
                name='Flour', quantity=Decimal('500'), source='production'
            ),
            lines,
            org,
        )

        rows = await rows_of(real_async_db_session, line.shopping_list_id)
        assert sorted(r.quantity for r in rows) == [Decimal('200'), Decimal('300')]
