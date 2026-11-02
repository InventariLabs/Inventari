"""A deletion or a restore movement names its author.

The receipt, the edit, the consumption and the disposal all travel through
the record bridge with the hand that caused them, so the Movements journal
reads "Kto: Admin". The soft delete and its pair took the same bridge
without the hand: the row landed with an empty ``created_by`` and the
journal answered "—".
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.item import Item
from app.models.stock_move import StockMove
from app.services.items import delete_item, restore_item


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
async def test_a_deletion_move_names_its_author(
    real_async_db_session,
    async_test_household,
    async_test_user,
    async_test_category,
    async_test_storage_location,
):
    """Archiving five leaves a movement whose author is the archiver."""
    db = real_async_db_session
    item = await _stocked_item(
        db,
        async_test_household,
        async_test_category,
        async_test_storage_location,
        'Router',
    )

    await delete_item(db, item, async_test_user, reason='retired')
    await db.commit()

    moves = await _moves_for_item(db, async_test_household.id, item.id)
    assert len(moves) == 1
    assert moves[0].quantity == Decimal('5')
    assert moves[0].created_by == async_test_user.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_restore_move_names_its_author(
    real_async_db_session,
    async_test_household,
    async_test_user,
    async_test_category,
    async_test_storage_location,
):
    """Bringing five back leaves a movement whose author is the restorer."""
    db = real_async_db_session
    item = await _stocked_item(
        db,
        async_test_household,
        async_test_category,
        async_test_storage_location,
        'Switch',
    )

    await delete_item(db, item, async_test_user, reason='lost')
    await db.commit()
    await restore_item(db, item, async_test_user)
    await db.commit()

    moves = await _moves_for_item(db, async_test_household.id, item.id)
    assert len(moves) == 2
    assert [move.created_by for move in moves] == [
        async_test_user.id,
        async_test_user.id,
    ]
