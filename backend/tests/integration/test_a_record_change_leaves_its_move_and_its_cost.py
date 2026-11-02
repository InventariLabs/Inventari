"""A record's own change leaves exactly the movement and the cost it caused.

``apply_quantity_change_async`` is the last step of every per-record write —
a typed quantity, a scan, a stock take's counted number — and
``_post_the_change_async`` is what it leaves behind: the ledger line, the
cost layer and the batch and owner the change belongs to. A mutation run
over those two functions found that a change could post the wrong delta, no
cost, no movement at all, or the movement under another name without a test
noticing, because the tests around them asked what the shelf held and not
what the posting wrote.

These tests ask the posting directly, record by record.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError, StockUnavailableError
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.warehouse.models import Document
from app.schemas.validators import QUANTITY_MAX
from app.services.items._stock_quant import apply_quantity_change_async
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.integration


@pytest.fixture
async def room(real_async_db_session: AsyncSession) -> dict[str, object]:
    db = real_async_db_session
    organization = Organization(
        name=f'Posting edges {uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'locations', 'categories'],
    )
    db.add(organization)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, organization, email=f'posting-{uuid4().hex[:8]}@example.test'
    )
    storage_type = StorageType(
        name='Shelf',
        type_code=f'SHELF_{uuid4().hex[:6]}',
        behavior_mode='NONE',
        organization_id=organization.id,
    )
    db.add(storage_type)
    await db.flush()
    shelf = StorageLocation(
        organization_id=organization.id,
        storage_type_id=storage_type.id,
        name=f'Posting shelf {uuid4().hex[:6]}',
        created_by=user.id,
    )
    template = ProductTemplate(
        name=f'Posting product {uuid4().hex[:8]}',
        organization_id=organization.id,
    )
    db.add(shelf)
    db.add(template)
    await db.commit()
    return {
        'db': db,
        'org': organization,
        'user': user,
        'shelf': shelf,
        'template': template,
    }


async def _stock(
    room: dict[str, object],
    quantity: str,
    *,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    purchase_price: str | None = None,
) -> Item:
    db: AsyncSession = room['db']  # type: ignore[assignment]
    keeper = await shelf_keeper(db, room['org'].id)  # type: ignore[attr-defined]
    return await put_on_shelf(
        db,
        keeper,
        room['template'],  # type: ignore[arg-type]
        room['shelf'].id,  # type: ignore[attr-defined]
        quantity,
        lot_id=lot_id,
        owner_id=owner_id,
        purchase_price=purchase_price,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('owned', [True, False])
async def test_quantity_postings_and_adoption_keep_the_owner(
    room: dict[str, object], owned: bool
) -> None:
    db = cast(AsyncSession, room['db'])
    org = cast(Organization, room['org'])
    shelf = cast(StorageLocation, room['shelf'])
    template = cast(ProductTemplate, room['template'])
    owner = Partner(organization_id=org.id, name='Stock owner', type='CUSTOMER')
    lot = StockLot(
        organization_id=org.id, product_template_id=template.id, name='OWNER-BATCH'
    )
    db.add_all([owner, lot])
    await db.flush()
    owner_id = owner.id if owned else None
    item = await _stock(room, '5', lot_id=lot.id, owner_id=owner_id)
    await apply_quantity_change_async(db, item, Decimal('4'), outflow_reason='USED')
    await apply_quantity_change_async(db, item, Decimal('6'))

    cardless = Item(
        name=f'Cardless owner {uuid4().hex[:6]}',
        organization_id=org.id,
        storage_location_id=shelf.id,
        owner_id=owner_id,
        quantity=Decimal('2'),
    )
    db.add(cardless)
    await db.flush()
    await apply_quantity_change_async(db, cardless, Decimal('3'))
    await db.commit()

    moves = await _moves(room, item.id)
    assert len(moves) == 3
    assert all(move.owner_id == owner_id and move.lot_id == lot.id for move in moves)
    opening = (
        await db.scalars(
            select(StockMove).where(
                StockMove.reference_type == 'opening_balance',
                StockMove.reference_id == cardless.id,
            )
        )
    ).one()
    assert opening.owner_id == owner_id


async def _moves(room: dict[str, object], item_id: UUID) -> list[StockMove]:
    db: AsyncSession = room['db']  # type: ignore[assignment]
    return list(
        (
            await db.scalars(
                select(StockMove)
                .where(
                    StockMove.organization_id == room['org'].id,  # type: ignore[attr-defined]
                    StockMove.reference_type == 'item',
                    StockMove.reference_id == item_id,
                )
                .order_by(StockMove.created_at, StockMove.id)
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_an_increase_leaves_the_delta_under_the_records_name(
    room: dict[str, object],
) -> None:
    """The movement is the delta, named by the record it changed and its hand."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5', purchase_price='1.00')
    await db.commit()

    await apply_quantity_change_async(
        db,
        item,
        Decimal('8'),
        unit_cost=Decimal('2.00'),
        user_id=room['user'].id,  # type: ignore[attr-defined]
    )
    await db.commit()

    assert item.quantity == Decimal('8')
    moves = await _moves(room, item.id)
    assert len(moves) == 2, 'the opening and the change are two movements'
    move = moves[-1]
    assert move.quantity == Decimal('3')
    assert move.to_location_id == room['shelf'].id  # type: ignore[attr-defined]
    assert move.reference_type == 'item'
    assert move.reference_id == item.id
    assert move.created_by == room['user'].id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_an_increase_leaves_a_cost_layer_at_the_price_it_was_given(
    room: dict[str, object],
) -> None:
    """A receipt the caller priced is valued at that price, not left unvalued."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5', purchase_price='1.00')
    await db.commit()

    await apply_quantity_change_async(db, item, Decimal('8'), unit_cost=Decimal('2.00'))
    await db.commit()

    layer = (
        await db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id == room['org'].id,  # type: ignore[attr-defined]
                StockValuationLayer.product_template_id == item.template_id,
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.quantity == Decimal('3'),
            )
        )
    ).one()
    assert layer.unit_cost == Decimal('2.0000')
    assert layer.remaining_qty == Decimal('3')


@pytest.mark.asyncio
async def test_a_change_of_one_posts_one(room: dict[str, object]) -> None:
    """A delta of one is a movement, not a rounding of zero."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    await apply_quantity_change_async(db, item, Decimal('6'))
    await db.commit()

    moves = await _moves(room, item.id)
    assert [move.quantity for move in moves][-1] == Decimal('1')
    assert len(moves) == 2


@pytest.mark.asyncio
async def test_a_change_to_the_same_number_writes_nothing(
    room: dict[str, object],
) -> None:
    """A number that did not move has no movement to explain."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    before = len(await _moves(room, item.id))
    before_layers = await db.scalar(
        select(func.count())
        .select_from(StockValuationLayer)
        .where(StockValuationLayer.organization_id == room['org'].id)  # type: ignore[attr-defined]
    )

    await apply_quantity_change_async(db, item, Decimal('5'))
    await db.commit()

    assert len(await _moves(room, item.id)) == before
    assert (
        await db.scalar(
            select(func.count())
            .select_from(StockValuationLayer)
            .where(StockValuationLayer.organization_id == room['org'].id)  # type: ignore[attr-defined]
        )
        == before_layers
    )


@pytest.mark.asyncio
async def test_the_ceiling_refuses_before_anything_is_written(
    room: dict[str, object],
) -> None:
    """A number past what the column stores is refused, and the record stays."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    before = len(await _moves(room, item.id))

    with pytest.raises(ServiceRejectionError):
        await apply_quantity_change_async(db, item, QUANTITY_MAX + Decimal('1'))

    assert item.quantity == Decimal('5')
    assert len(await _moves(room, item.id)) == before


@pytest.mark.asyncio
async def test_a_consuming_decrease_of_a_held_batch_is_refused(
    room: dict[str, object],
) -> None:
    """Eating a recalled batch is refused; correcting its number is not."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    lot = StockLot(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        product_template_id=room['template'].id,  # type: ignore[attr-defined]
        name=f'HELD-{uuid4().hex[:6]}',
        status=LotStatus.HELD.value,
    )
    db.add(lot)
    await db.flush()
    item = await _stock(room, '3', lot_id=lot.id)
    item_id, lot_id = item.id, lot.id
    await db.commit()

    with pytest.raises(ValueError, match='cannot be consumed'):
        await apply_quantity_change_async(
            db,
            item,
            Decimal('2'),
            outflow_reason=ItemAction.USED.value,
        )
    await db.rollback()

    # A plain edit states the number and says nothing about why: a held
    # batch's count may be corrected, which is not consuming it.
    item = await db.get(Item, item_id)
    await apply_quantity_change_async(db, item, Decimal('2'))
    await db.commit()
    assert item.quantity == Decimal('2')

    # A count may also name the batch it corrected.
    await apply_quantity_change_async(db, item, Decimal('1'), lot_id=lot_id)
    await db.commit()
    assert item.quantity == Decimal('1')


@pytest.mark.asyncio
async def test_the_batch_check_never_names_another_organizations_batch(
    room: dict[str, object],
) -> None:
    """The consumable check reads the batch inside the record's organization only.

    Nothing in the schema ties a record's ``lot_id`` to a batch of its own
    organization, so a record can point at another tenant's batch. The check
    must then answer as for a batch that does not exist: a lookup by bare id
    would refuse the change with the other organization's batch name and
    status in the sentence.
    """
    db: AsyncSession = room['db']  # type: ignore[assignment]
    other = Organization(name=f'Other tenant {uuid4().hex[:8]}')
    db.add(other)
    await db.flush()
    other_template = ProductTemplate(
        name=f'Other product {uuid4().hex[:8]}', organization_id=other.id
    )
    db.add(other_template)
    await db.flush()
    foreign_name = f'FOREIGN-{uuid4().hex[:6]}'
    foreign = StockLot(
        organization_id=other.id,
        product_template_id=other_template.id,
        name=foreign_name,
        status=LotStatus.HELD.value,
    )
    db.add(foreign)
    await db.flush()
    item = await _stock(room, '3')
    item.lot_id = foreign.id
    await db.commit()

    await apply_quantity_change_async(
        db,
        item,
        Decimal('2'),
        outflow_reason=ItemAction.USED.value,
    )
    await db.rollback()


@pytest.mark.asyncio
async def test_a_cardless_records_opening_names_the_hand_that_made_it(
    room: dict[str, object],
) -> None:
    """The opening a cardless record adopts is posted by the person editing it."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    record = Item(
        name=f'Cardless {uuid4().hex[:6]}',
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        storage_location_id=room['shelf'].id,  # type: ignore[attr-defined]
        quantity=Decimal('5'),
    )
    db.add(record)
    await db.flush()

    await apply_quantity_change_async(
        db,
        record,
        Decimal('6'),
        user_id=room['user'].id,  # type: ignore[attr-defined]
    )
    await db.commit()

    opening = (
        await db.scalars(
            select(StockMove).where(
                StockMove.organization_id == room['org'].id,  # type: ignore[attr-defined]
                StockMove.reference_type == 'opening_balance',
            )
        )
    ).one()
    assert opening.quantity == Decimal('5')
    assert opening.created_by == room['user'].id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_cardless_records_opening_is_not_valued_by_a_door_that_owns_its_valuation(
    room: dict[str, object],
) -> None:
    """A door that writes its own valuation leaves the opening's layers alone."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    record = Item(
        name=f'Cardless unvalued {uuid4().hex[:6]}',
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        storage_location_id=room['shelf'].id,  # type: ignore[attr-defined]
        quantity=Decimal('5'),
    )
    db.add(record)
    await db.flush()

    await apply_quantity_change_async(
        db,
        record,
        Decimal('6'),
        sync_valuation=False,
    )
    await db.commit()

    opening = (
        await db.scalars(
            select(StockMove).where(
                StockMove.organization_id == room['org'].id,  # type: ignore[attr-defined]
                StockMove.reference_type == 'opening_balance',
            )
        )
    ).one()
    assert opening.quantity == Decimal('5')
    layers = await db.scalar(
        select(func.count())
        .select_from(StockValuationLayer)
        .where(StockValuationLayer.organization_id == room['org'].id)  # type: ignore[attr-defined]
    )
    assert layers == 0, 'the opening was valued by a door that owns its valuation'


@pytest.mark.asyncio
async def test_a_count_naming_another_batch_moves_that_batch(
    room: dict[str, object],
) -> None:
    """A count corrects the batch it names, even when the record names another.

    The record keeps its own batch; the movement says which batch the
    counted difference belongs to.
    """
    db: AsyncSession = room['db']  # type: ignore[assignment]
    first = StockLot(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        product_template_id=room['template'].id,  # type: ignore[attr-defined]
        name=f'FIRST-{uuid4().hex[:6]}',
    )
    named = StockLot(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        product_template_id=room['template'].id,  # type: ignore[attr-defined]
        name=f'NAMED-{uuid4().hex[:6]}',
    )
    db.add_all([first, named])
    await db.flush()
    item = await _stock(room, '5', lot_id=first.id)
    await _stock(room, '2', lot_id=named.id)
    item_id, named_id = item.id, named.id
    await db.commit()

    item = await db.get(Item, item_id)
    await apply_quantity_change_async(db, item, Decimal('4'), lot_id=named_id)
    await db.commit()

    moves = await _moves(room, item_id)
    assert moves[-1].lot_id == named_id
    assert moves[-1].from_location_id == room['shelf'].id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_receipt_of_a_batch_moves_it_under_that_batch(
    room: dict[str, object],
) -> None:
    """The movement names the record's own batch; a receipt is not batchless."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    lot = StockLot(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        product_template_id=room['template'].id,  # type: ignore[attr-defined]
        name=f'RECEIPT-{uuid4().hex[:6]}',
    )
    db.add(lot)
    await db.flush()
    item = await _stock(room, '2', lot_id=lot.id)
    lot_id = lot.id
    await db.commit()

    await apply_quantity_change_async(db, item, Decimal('3'))
    await db.commit()

    move = (await _moves(room, item.id))[-1]
    assert move.lot_id == lot_id
    assert move.to_location_id == room['shelf'].id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_decrease_keeps_the_batch_and_the_reason_it_left(
    room: dict[str, object],
) -> None:
    """A use leaves the movement under its batch, and its cost says why."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    lot = StockLot(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        product_template_id=room['template'].id,  # type: ignore[attr-defined]
        name=f'USED-{uuid4().hex[:6]}',
    )
    db.add(lot)
    await db.flush()
    item = await _stock(room, '5', lot_id=lot.id)
    lot_id = lot.id
    await db.commit()

    await apply_quantity_change_async(
        db,
        item,
        Decimal('3'),
        outflow_reason=ItemAction.USED.value,
        user_id=room['user'].id,  # type: ignore[attr-defined]
    )
    await db.commit()

    move = (await _moves(room, item.id))[-1]
    assert move.lot_id == lot_id
    assert move.from_location_id == room['shelf'].id  # type: ignore[attr-defined]
    assert move.created_by == room['user'].id  # type: ignore[attr-defined]
    layer = (
        await db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id == room['org'].id,  # type: ignore[attr-defined]
                StockValuationLayer.direction == 'OUT',
                StockValuationLayer.quantity == Decimal('2'),
            )
        )
    ).one()
    assert layer.reason == ItemAction.USED.value
    assert layer.item_id == item.id


@pytest.mark.asyncio
async def test_a_one_unit_receipt_goes_in_not_out(room: dict[str, object]) -> None:
    """A delta of one is a receipt in both directions of the branch."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    await apply_quantity_change_async(db, item, Decimal('6'))
    await db.commit()

    move = (await _moves(room, item.id))[-1]
    assert move.to_location_id == room['shelf'].id  # type: ignore[attr-defined]
    assert move.from_location_id is None


@pytest.mark.asyncio
async def test_a_price_of_one_is_still_a_price(room: dict[str, object]) -> None:
    """The cheapest stated price is a price, not the unpriced fallback."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    await apply_quantity_change_async(db, item, Decimal('6'), unit_cost=Decimal('1.00'))
    await db.commit()

    layer = (
        await db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id == room['org'].id,  # type: ignore[attr-defined]
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.quantity == Decimal('1'),
            )
        )
    ).one()
    assert layer.unit_cost == Decimal('1.0000')
    assert layer.cost_basis == 'stated'


@pytest.mark.asyncio
async def test_a_zero_price_is_no_price(room: dict[str, object]) -> None:
    """A stated zero values nothing; the receipt falls back to the org's rate."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    await apply_quantity_change_async(db, item, Decimal('6'), unit_cost=Decimal('0'))
    await db.commit()

    layer = (
        await db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id == room['org'].id,  # type: ignore[attr-defined]
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.quantity == Decimal('1'),
            )
        )
    ).one()
    assert layer.cost_basis != 'stated'


@pytest.mark.asyncio
async def test_a_short_named_batch_is_refused_though_another_covers_it(
    room: dict[str, object],
) -> None:
    """A count that names its batch is held to that batch, not to a sibling."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    lot = StockLot(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        product_template_id=room['template'].id,  # type: ignore[attr-defined]
        name=f'COUNTED-{uuid4().hex[:6]}',
    )
    db.add(lot)
    await db.flush()
    item = await _stock(room, '3', lot_id=lot.id)
    lot_id = lot.id
    await db.commit()
    # An order holds two of the three, so stating the batch at one leaves
    # its grain promising more than it holds.
    document = Document(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        type='OUT',
        number=f'TMP-{uuid4().hex[:8]}',
        created_by=room['user'].id,  # type: ignore[attr-defined]
    )
    db.add(document)
    await db.flush()
    reservation = await core_api.stock.reserve_for_document_async(
        db,
        room['org'].id,  # type: ignore[attr-defined]
        room['template'].id,  # type: ignore[attr-defined]
        room['shelf'].id,  # type: ignore[attr-defined]
        Decimal('2'),
        'FIFO',
        document_id=document.id,
    )
    assert reservation.success is True
    await db.commit()

    with pytest.raises(ValueError):
        await apply_quantity_change_async(db, item, Decimal('1'), lot_id=lot_id)


@pytest.mark.asyncio
async def test_the_ceiling_refusal_names_the_bound_and_the_number(
    room: dict[str, object],
) -> None:
    """A refusal past what the column stores says which number and which bound."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    with pytest.raises(ServiceRejectionError) as refusal:
        await apply_quantity_change_async(db, item, QUANTITY_MAX + Decimal('1'))

    assert refusal.value.key == 'item_quantity_above_ceiling'
    assert refusal.value.kwargs['quantity'] == QUANTITY_MAX + Decimal('1')
    assert refusal.value.kwargs['ceiling'] == QUANTITY_MAX


@pytest.mark.asyncio
async def test_the_ceiling_itself_is_allowed(room: dict[str, object]) -> None:
    """The bound is the largest storable number, not the first refused one."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()

    await apply_quantity_change_async(db, item, QUANTITY_MAX)
    await db.commit()

    assert item.quantity == QUANTITY_MAX


@pytest.mark.asyncio
async def test_a_change_reads_the_number_again_under_the_lock(
    room: dict[str, object],
) -> None:
    """The posting works from what the row says now, not what the caller saw."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    await db.commit()
    item_id = item.id
    # Another hand moved the number after this object was read.
    await db.execute(
        Item.__table__.update()
        .where(Item.id == item_id)
        .values(quantity=Decimal('3'))
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    assert item.quantity == Decimal('5'), 'the caller holds the stale number'

    await apply_quantity_change_async(db, item, Decimal('6'))
    await db.commit()

    move = (await _moves(room, item_id))[-1]
    assert move.quantity == Decimal('3'), 'the change used the stale number'
    assert item.quantity == Decimal('6')


@pytest.mark.asyncio
async def test_a_decrease_below_its_holds_is_refused(
    room: dict[str, object],
) -> None:
    """Stating a shelf below what an order holds refuses rather than eats the order."""
    db: AsyncSession = room['db']  # type: ignore[assignment]
    item = await _stock(room, '5')
    item_id = item.id
    document = Document(
        organization_id=room['org'].id,  # type: ignore[attr-defined]
        type='OUT',
        number=f'TMP-{uuid4().hex[:8]}',
        created_by=room['user'].id,  # type: ignore[attr-defined]
    )
    db.add(document)
    await db.flush()
    await db.commit()
    await core_api.stock.reserve_for_document_async(
        db,
        room['org'].id,  # type: ignore[attr-defined]
        room['template'].id,  # type: ignore[attr-defined]
        room['shelf'].id,  # type: ignore[attr-defined]
        Decimal('3'),
        'FIFO',
        document_id=document.id,
    )
    await db.commit()
    item = await db.get(Item, item_id)

    with pytest.raises(StockUnavailableError) as refusal:
        await apply_quantity_change_async(db, item, Decimal('1'))

    assert refusal.value.code == StockUnavailableError.NOT_ENOUGH
    assert '2' in str(refusal.value), (
        'the refusal should say the two units the hold leaves available'
    )
