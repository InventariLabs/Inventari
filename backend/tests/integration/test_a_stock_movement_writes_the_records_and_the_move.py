"""One call states the records and writes the journal line that says so.

``core_api.stock_moves.create_async`` records a movement and changes no
record. Every path that opted out of the per-item bridge had to remember to
change the records and to write the movement, with the same numbers, and the
reconciliation's shelf-versus-ledger pair measured the days one of them
forgot. ``post_movement_async`` is the one operation that does both: it
states the records it is handed and writes the movement, so each assertion
below reads the shelf *and* the ledger.

It used to keep a quant beside the records and to draw by removal strategy
when no batch was named; the quant table is gone, and the draw by strategy
is ``take_from_the_records_async`` (``test_a_draw_writes_its_own_moves``).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.contracts import RecordPostDTO, UserContextDTO
from app.core.exceptions import StockUnavailableError
from app.core.public_api import core_api
from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemCreate
from app.services.items import create_item
from tests.integration._shelf import put_on_shelf, reserve_for_an_order

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def shelf_pair(
    real_async_db_session,
    async_test_household,
    async_test_user,
    async_test_storage_location,
):
    """A product with two batches, and a second shelf beside the first."""
    db = real_async_db_session
    org_id = async_test_household.id
    template = ProductTemplate(
        organization_id=org_id,
        name=f'Flour {uuid4().hex[:6]}',
        sku=f'SKU-{uuid4().hex[:8]}',
    )
    db.add(template)
    other = StorageLocation(
        organization_id=org_id,
        created_by=async_test_user.id,
        storage_type_id=async_test_storage_location.storage_type_id,
        name='Second shelf',
    )
    db.add(other)
    await db.flush()
    first_lot = StockLot(
        organization_id=org_id, product_template_id=template.id, name='L-1'
    )
    second_lot = StockLot(
        organization_id=org_id, product_template_id=template.id, name='L-2'
    )
    db.add_all([first_lot, second_lot])
    await db.commit()
    return {
        'org_id': org_id,
        'template_id': template.id,
        'here': async_test_storage_location.id,
        'there': other.id,
        'lots': (first_lot.id, second_lot.id),
        'user_id': async_test_user.id,
        'template': template,
        'user': async_test_user,
    }


async def _on_shelf(db, s, location_id: UUID, lot_id: UUID | None) -> Decimal:
    """What the shelf holds of the batch, as the records say; no group is none."""
    row = await db.scalar(
        select(ShelfRow).where(
            ShelfRow.organization_id == s['org_id'],
            ShelfRow.product_template_id == s['template_id'],
            ShelfRow.storage_location_id == location_id,
            ShelfRow.lot_id == lot_id if lot_id else ShelfRow.lot_id.is_(None),
        )
    )
    return row.quantity if row is not None else Decimal('0')


async def _moves(db, reference_id: UUID) -> list[StockMove]:
    return list(
        (
            await db.scalars(
                select(StockMove)
                .where(StockMove.reference_id == reference_id)
                .order_by(StockMove.quantity)
            )
        ).all()
    )


async def _seed(db, s, location_id: UUID, lot_id: UUID, quantity: str) -> Item:
    return await put_on_shelf(
        db, s['user'], s['template'], location_id, quantity, lot_id=lot_id
    )


async def test_goods_arriving_are_stated_and_leave_one_movement(
    real_async_db_session, shelf_pair
):
    db, s = real_async_db_session, shelf_pair
    lot = s['lots'][0]
    record = await _seed(db, s, s['here'], lot, '5')
    ref = uuid4()

    posted = await core_api.stock.post_movement_async(
        db,
        s['org_id'],
        s['template_id'],
        Decimal('3'),
        to_location_id=s['here'],
        lot_id=lot,
        reference_type='document',
        reference_id=ref,
        created_by=s['user_id'],
        records=[RecordPostDTO(item_id=record.id, new_quantity=Decimal('8'))],
    )

    assert await _on_shelf(db, s, s['here'], lot) == Decimal('8')
    [move] = await _moves(db, ref)
    assert (move.from_location_id, move.to_location_id) == (None, s['here'])
    assert (move.quantity, move.lot_id) == (Decimal('3'), lot)
    assert move.reference_type == 'document'
    assert [(p.lot_id, p.consumed) for p in posted] == [(lot, Decimal('3'))]


async def test_a_named_batch_moves_between_shelves_as_that_batch(
    real_async_db_session, shelf_pair
):
    db, s = real_async_db_session, shelf_pair
    lot = s['lots'][1]
    source = await _seed(db, s, s['here'], lot, '5')
    ref = uuid4()
    # The door opens the record the goods land on; the pass writes the
    # movement, so the bridge stays off.
    await create_item(
        db,
        ItemCreate(
            name=s['template'].name,
            location_id=s['there'],
            quantity=Decimal('2'),
            template_id=s['template_id'],
        ),
        UserContextDTO(id=s['user_id'], organization_id=s['org_id']),
        lot_id=lot,
        post_the_change=False,
    )

    await core_api.stock.post_movement_async(
        db,
        s['org_id'],
        s['template_id'],
        Decimal('2'),
        from_location_id=s['here'],
        to_location_id=s['there'],
        lot_id=lot,
        require_active_lot=False,
        reference_type='document',
        reference_id=ref,
        records=[RecordPostDTO(item_id=source.id, new_quantity=Decimal('3'))],
    )

    assert await _on_shelf(db, s, s['here'], lot) == Decimal('3')
    assert await _on_shelf(db, s, s['there'], lot) == Decimal('2')
    [move] = await _moves(db, ref)
    assert (move.from_location_id, move.to_location_id) == (s['here'], s['there'])
    assert (move.quantity, move.lot_id) == (Decimal('2'), lot)


async def test_a_refused_removal_writes_neither_half(real_async_db_session, shelf_pair):
    db, s = real_async_db_session, shelf_pair
    lot = s['lots'][0]
    record = await _seed(db, s, s['here'], lot, '5')
    await reserve_for_an_order(db, s['template'], s['here'], Decimal('4'))
    await db.commit()
    ref = uuid4()

    # Three of five leave, two stay — below the four an order holds.
    with pytest.raises(StockUnavailableError) as refusal:
        await core_api.stock.post_movement_async(
            db,
            s['org_id'],
            s['template_id'],
            Decimal('3'),
            from_location_id=s['here'],
            lot_id=lot,
            reference_type='document',
            reference_id=ref,
            records=[RecordPostDTO(item_id=record.id, new_quantity=Decimal('2'))],
        )
    assert refusal.value.code == StockUnavailableError.NOT_ENOUGH
    # The refusal comes before the movement is written; the record the pass
    # had stated goes back with the caller's transaction.
    assert await _moves(db, ref) == []
    await db.rollback()

    assert await _on_shelf(db, s, s['here'], lot) == Decimal('5')
    assert await _moves(db, ref) == []


async def test_a_movement_needs_somewhere_to_come_from_or_go_to(
    real_async_db_session, shelf_pair
):
    db, s = real_async_db_session, shelf_pair

    with pytest.raises(TypeError):
        await core_api.stock.post_movement_async(
            db,
            s['org_id'],
            s['template_id'],
            Decimal('1'),
            reference_type='document',
            reference_id=uuid4(),
        )
