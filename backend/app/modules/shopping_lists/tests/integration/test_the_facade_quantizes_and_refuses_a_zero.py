"""The facade must guard the quantity itself, not borrow the consumers' guard.

``add_items_async`` is the public, cross-module door — it built
``ShoppingListItem`` straight from ``ShoppingListItemCreateDTO``, whose only
quantity bound is ``gt=0``, bypassing both places the protection lives today
(the quantizing validators on ``ShoppingListItemCreate`` and the zero refusal
in ``bulk_add_items``). Both of today's callers quantize before they call, so
nothing is broken right now — and that is precisely the shape a confused
deputy has before someone writes the third caller. A stored zero is a row no
read schema accepts: the list stops opening and nothing in the interface can
undo it.

The response half: the echo used to be validated from the in-memory objects —
``db.refresh(item, ['category'])`` answered only the relationship — so it
could name a number the column had silently rounded away.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ShoppingListItemCreateDTO
from app.core.exceptions import ServiceRejectionError
from app.i18n.service import set_current_lang
from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

#: Below the store's three decimal places — passes the DTO's ``gt=0``, and
#: the column would keep it as a silent zero.
ROUNDS_TO_ZERO = Decimal('0.0004')


async def a_list(
    db: AsyncSession, user: User, name: str = 'Facade List'
) -> ShoppingList:
    assert user.organization_id is not None
    shopping_list = ShoppingList(
        organization_id=user.organization_id,
        created_by=user.id,
        name=name,
    )
    db.add(shopping_list)
    await db.flush()
    await db.refresh(shopping_list)
    return shopping_list


async def rows_of(db: AsyncSession, list_id: UUID) -> list[ShoppingListItem]:
    result = await db.scalars(
        ShoppingListItem.__table__.select().where(
            ShoppingListItem.shopping_list_id == list_id
        )
    )
    return list(result)


@pytest.mark.integration
class TestAddItemsQuantity:
    @pytest.mark.asyncio
    async def test_a_quantity_that_rounds_to_zero_is_refused(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        shopping_list = await a_list(real_async_db_session, async_test_user)

        with pytest.raises(ServiceRejectionError) as refused:
            await shopping_lists_api.add_items_async(
                real_async_db_session,
                shopping_list.id,
                [ShoppingListItemCreateDTO(name='Flour', quantity=ROUNDS_TO_ZERO)],
                _org_of(async_test_user),
            )

        assert refused.value.key == 'shopping_list_item_quantity_rounds_to_zero'
        assert await rows_of(real_async_db_session, shopping_list.id) == []

    @pytest.mark.asyncio
    async def test_the_zero_refusal_states_the_step_and_the_quantity_in_words(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        """The sentence is the product: both numbers are written for the
        reader, in the reader's decimal mark, and the quantity is the one
        the column would have kept — the same value the CRUD door states."""
        shopping_list = await a_list(real_async_db_session, async_test_user)

        set_current_lang('pl')
        try:
            with pytest.raises(ServiceRejectionError) as refused:
                await shopping_lists_api.add_items_async(
                    real_async_db_session,
                    shopping_list.id,
                    [ShoppingListItemCreateDTO(name='Flour', quantity=ROUNDS_TO_ZERO)],
                    _org_of(async_test_user),
                )
        finally:
            set_current_lang('en')

        assert refused.value.kwargs == {'quantity': '0', 'smallest': '0,001'}
        sentence = refused.value.sentence('pl')
        assert '.' not in sentence.replace('szt.', '')
        assert '{' not in sentence

    @pytest.mark.asyncio
    async def test_the_ceiling_refusal_writes_both_numbers_in_the_readers_mark(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        shopping_list = await a_list(real_async_db_session, async_test_user)

        set_current_lang('pl')
        try:
            with pytest.raises(ServiceRejectionError) as refused:
                await shopping_lists_api.add_items_async(
                    real_async_db_session,
                    shopping_list.id,
                    [
                        ShoppingListItemCreateDTO(
                            name='Flour', quantity=Decimal('1000000000.5')
                        )
                    ],
                    _org_of(async_test_user),
                )
        finally:
            set_current_lang('en')

        assert refused.value.key == 'shopping_list_item_quantity_above_ceiling'
        sentence = refused.value.sentence('pl')
        assert '1000000000,5' in sentence
        assert '999999999,999' in sentence
        assert '.' not in sentence

    @pytest.mark.asyncio
    async def test_a_refusal_answers_the_whole_call_not_the_remainder(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        """The same shape as bulk_add_items: no half-written batch."""
        shopping_list = await a_list(real_async_db_session, async_test_user)
        batch = [
            ShoppingListItemCreateDTO(name='Flour', quantity=1),
            ShoppingListItemCreateDTO(name='Sugar', quantity=ROUNDS_TO_ZERO),
        ]

        with pytest.raises(ServiceRejectionError):
            await shopping_lists_api.add_items_async(
                real_async_db_session,
                shopping_list.id,
                batch,
                _org_of(async_test_user),
            )

        assert await rows_of(real_async_db_session, shopping_list.id) == []

    @pytest.mark.asyncio
    async def test_the_quantity_is_quantized_to_the_store_precision(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        """Half-up at three places — what the reader was told is what is kept."""
        shopping_list = await a_list(real_async_db_session, async_test_user)

        added = await shopping_lists_api.add_items_async(
            real_async_db_session,
            shopping_list.id,
            [ShoppingListItemCreateDTO(name='Flour', quantity=Decimal('1.0005'))],
            _org_of(async_test_user),
        )

        assert [item.quantity for item in added] == [Decimal('1.001')]

    @pytest.mark.asyncio
    async def test_the_echo_carries_what_the_column_kept(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        """The echo is read back after the flush, not validated from the
        object built before it. estimated_price is the honest proof: the
        column is numeric(10, 2) and rounds 1.999 to 2.00, and no schema
        on the way in touches it — only a read-back can tell the two
        numbers apart."""
        shopping_list = await a_list(real_async_db_session, async_test_user)

        added = await shopping_lists_api.add_items_async(
            real_async_db_session,
            shopping_list.id,
            [
                ShoppingListItemCreateDTO(
                    name='Flour',
                    quantity=1,
                    estimated_price=Decimal('1.999'),
                )
            ],
            _org_of(async_test_user),
        )

        assert [item.estimated_price for item in added] == [Decimal('2.00')]


def _org_of(user: User) -> UUID:
    assert user.organization_id is not None
    return user.organization_id
