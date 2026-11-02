"""A consumption or disposal movement names its author.

The receipt and the quantity edit both travel through the record bridge
with the hand that caused them, so the Movements journal reads "Kto:
Admin". Consume and discard took the same bridge without the hand: the
row landed with an empty ``created_by`` and the journal answered "—".
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.item import Item
from app.models.stock_move import StockMove
from app.schemas.item import ItemConsumeRequest, ItemDiscardRequest
from app.services.items import consume_item, discard_item


async def _moves_for_item(session, org_id, item_id):
    return list(
        (
            await session.scalars(
                select(StockMove).where(
                    StockMove.organization_id == org_id,
                    StockMove.reference_type == 'item',
                    StockMove.reference_id == item_id,
                )
            )
        ).all()
    )


async def _stocked_item(db, household, category, storage, name):
    def _make(session):
        item = Item(
            organization_id=household.id,
            storage_location_id=storage.id,
            category_id=category.id,
            template_id=None,
            name=name,
            quantity=Decimal('5'),
        )
        session.add(item)
        session.flush()
        return item

    item = await db.run_sync(_make)
    await db.commit()
    return item


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_consumption_move_names_its_author(
    real_async_db_session,
    async_test_household,
    async_test_user,
    async_test_category,
    async_test_storage_location,
):
    """Taking two off five leaves a movement whose author is the taker."""
    db = real_async_db_session
    item = await _stocked_item(
        db,
        async_test_household,
        async_test_category,
        async_test_storage_location,
        'Jam',
    )

    await consume_item(
        db,
        item,
        ItemConsumeRequest(quantity=Decimal('2'), reason='eaten'),
        async_test_user,
    )
    await db.commit()

    moves = await _moves_for_item(db, async_test_household.id, item.id)
    assert len(moves) == 1
    outflow = moves[0]
    assert outflow.quantity == Decimal('2')
    assert outflow.from_location_id == async_test_storage_location.id
    assert outflow.created_by == async_test_user.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_disposal_move_names_its_author(
    real_async_db_session,
    async_test_household,
    async_test_user,
    async_test_category,
    async_test_storage_location,
):
    """Throwing one away leaves a movement whose author is the thrower."""
    db = real_async_db_session
    item = await _stocked_item(
        db,
        async_test_household,
        async_test_category,
        async_test_storage_location,
        'Yoghurt',
    )

    await discard_item(
        db,
        item,
        ItemDiscardRequest(quantity=Decimal('1'), reason='expired'),
        async_test_user,
    )
    await db.commit()

    moves = await _moves_for_item(db, async_test_household.id, item.id)
    assert len(moves) == 1
    outflow = moves[0]
    assert outflow.quantity == Decimal('1')
    assert outflow.from_location_id == async_test_storage_location.id
    assert outflow.created_by == async_test_user.id
