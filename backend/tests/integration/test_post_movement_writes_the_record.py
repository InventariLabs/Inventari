"""``post_movement_async`` writes the record it is handed, in the same pass.

The door that knows the record and the service that writes the ledger used
to make two transitions of one operation — the record's number changed first,
in the door, and the movement followed in a second call that took its own
locks. Under the one-number state model (ADR-022) the service takes the
record changes as they are (``records=``) and applies them under the anchor
locks it takes up front, beside the movement.

The second shape this pins is the correction's: a correction restates one
named grain — the batch-less one too, when the original line named no batch.
What leaves is always the grain the call names (``lot_id``, ``owner_id``),
never one a removal strategy would pick, and once the records are stated that
grain must still cover its reservation rows, or the pass is refused.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import RecordPostDTO
from app.core.exceptions import StockUnavailableError
from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.services._stock_quant_ops import post_movement_async
from tests.integration._shelf import put_on_shelf, reserve_for_an_order, shelf_keeper

pytestmark = pytest.mark.integration


async def _sow(
    db: AsyncSession,
    organization_id: UUID,
    template: ProductTemplate,
    location_id: UUID,
    quantity: Decimal,
    *,
    lot_id: UUID | None = None,
) -> Item:
    keeper = await shelf_keeper(db, organization_id)
    return await put_on_shelf(
        db, keeper, template, location_id, quantity, lot_id=lot_id
    )


@pytest.fixture
async def scene(real_async_db_session: AsyncSession) -> dict[str, Any]:
    from app.models.storage_type import StorageType
    from app.models.uom import Uom, UomCategory

    db = real_async_db_session
    org = Organization(
        name=f'Post Movement Org {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    keeper = await ModuleTestHelper.create_user_async(
        db, org, email=f'keeper_{uuid4().hex[:8]}@test.com'
    )

    category = UomCategory(name=f'Weight {uuid4().hex[:6]}', organization_id=org.id)
    db.add(category)
    await db.flush()
    uom = Uom(
        name='Kilogram',
        symbol='kg',
        category_id=category.id,
        organization_id=org.id,
        factor=1.0,
        is_reference=True,
    )
    db.add(uom)
    await db.flush()
    template = ProductTemplate(
        name=f'Rye flour {uuid4().hex[:6]}', organization_id=org.id, uom_id=uom.id
    )
    db.add(template)
    await db.flush()
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    shelf = StorageLocation(
        organization_id=org.id,
        storage_type_id=storage_type.id,
        name=f'Post Movement Shelf {uuid4().hex[:6]}',
        created_by=keeper.id,
    )
    other = StorageLocation(
        organization_id=org.id,
        storage_type_id=storage_type.id,
        name=f'Post Movement Other Shelf {uuid4().hex[:6]}',
        created_by=keeper.id,
    )
    db.add_all([shelf, other])
    await db.commit()
    return {
        'org': org,
        'template': template,
        'shelf': shelf,
        'other': other,
    }


async def _on_shelf(
    db: AsyncSession, org_id: UUID, template_id: UUID, location_id: UUID
) -> Decimal:
    """What the shelf holds of the product, every batch together, as the records say."""
    rows = (
        await db.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == org_id,
                ShelfRow.product_template_id == template_id,
                ShelfRow.storage_location_id == location_id,
            )
        )
    ).all()
    return sum((row.quantity for row in rows), Decimal('0'))


async def _item(db: AsyncSession, item_id: UUID) -> Item:
    await db.commit()
    return (
        await db.scalars(
            select(Item)
            .where(Item.id == item_id)
            .execution_options(populate_existing=True)
        )
    ).one()


@pytest.mark.asyncio
async def test_a_pass_with_neither_end_names_the_missing_argument(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """A movement with no shelf on either end is the caller's bug, said as one."""
    db = real_async_db_session

    with pytest.raises(TypeError) as refusal:
        await post_movement_async(
            db,
            scene['org'].id,
            scene['template'].id,
            Decimal('1'),
            reference_type='item',
            reference_id=uuid4(),
        )

    assert str(refusal.value) == (
        'post_movement_async needs from_location_id or to_location_id'
    )


async def test_a_record_handed_over_is_written_in_the_pass(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']

    record = await _sow(real_async_db_session, org.id, template, shelf.id, Decimal('5'))
    await real_async_db_session.commit()

    posted = await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('3'),
        to_location_id=shelf.id,
        reference_type='document',
        reference_id=org.id,
        records=[
            RecordPostDTO(
                item_id=record.id,
                new_quantity=Decimal('8'),
                history={'document_type': 'IN', 'document_number': 'PM-1'},
            )
        ],
    )

    assert [part.consumed for part in posted] == [Decimal('3')]
    item = await _item(real_async_db_session, record.id)
    assert item.quantity == Decimal('8')
    assert await _on_shelf(
        real_async_db_session, org.id, template.id, shelf.id
    ) == Decimal('8')
    move = (
        await real_async_db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == org.id,
                StockMove.reference_id == org.id,
            )
        )
    ).first()
    assert move is not None
    assert move.quantity == Decimal('3')
    assert move.to_location_id == shelf.id


async def test_the_movement_takes_the_batch_it_is_named(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']

    lot = StockLot(
        organization_id=org.id,
        product_template_id=template.id,
        name=f'LOT-{uuid4().hex[:6]}',
    )
    real_async_db_session.add(lot)
    await real_async_db_session.flush()
    await _sow(
        real_async_db_session, org.id, template, shelf.id, Decimal('4'), lot_id=lot.id
    )
    batchless = await _sow(
        real_async_db_session, org.id, template, shelf.id, Decimal('6')
    )
    await real_async_db_session.commit()

    # A correction restates the batch-less grain: a strategy would read
    # expiry and could take the lot's stock instead.
    await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('2'),
        from_location_id=shelf.id,
        lot_id=None,
        require_active_lot=False,
        reference_type='document',
        reference_id=org.id,
        records=[RecordPostDTO(item_id=batchless.id, new_quantity=Decimal('4'))],
    )

    item = await _item(real_async_db_session, batchless.id)
    assert item.quantity == Decimal('4')
    assert await _on_shelf(
        real_async_db_session, org.id, template.id, shelf.id
    ) == Decimal('8')


async def test_a_grain_left_short_of_its_holds_is_refused(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """The records stated first, then the grain they left: short of its holds, refused."""
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']

    record = await _sow(real_async_db_session, org.id, template, shelf.id, Decimal('5'))
    await reserve_for_an_order(real_async_db_session, template, shelf.id, Decimal('3'))
    await real_async_db_session.commit()
    record_id = record.id

    # Four of five leave, one stays — below the three an order holds.
    with pytest.raises(StockUnavailableError) as refusal:
        await post_movement_async(
            real_async_db_session,
            org.id,
            template.id,
            Decimal('4'),
            from_location_id=shelf.id,
            lot_id=None,
            require_active_lot=False,
            reference_type='document',
            reference_id=org.id,
            records=[RecordPostDTO(item_id=record_id, new_quantity=Decimal('1'))],
        )
    assert refusal.value.code == StockUnavailableError.NOT_ENOUGH
    await real_async_db_session.rollback()

    item = await _item(real_async_db_session, record_id)
    assert item.quantity == Decimal('5'), 'the refused pass took the record back'


async def test_a_receipt_names_the_shelf_it_arrived_on(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """What the pass reports arriving says where it arrived."""
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']

    posted = await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('2'),
        to_location_id=shelf.id,
        reference_type='document',
        reference_id=org.id,
    )

    assert [part.storage_location_id for part in posted] == [shelf.id]
    assert [part.consumed for part in posted] == [Decimal('2')]


async def test_an_issue_names_the_shelf_it_left(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """What the pass reports leaving says which shelf gave it up."""
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']

    record = await _sow(real_async_db_session, org.id, template, shelf.id, Decimal('5'))
    await real_async_db_session.commit()

    posted = await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('2'),
        from_location_id=shelf.id,
        reference_type='document',
        reference_id=org.id,
        records=[RecordPostDTO(item_id=record.id, new_quantity=Decimal('3'))],
    )

    assert [part.storage_location_id for part in posted] == [shelf.id]


async def test_a_move_names_the_shelf_it_left(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """A move has two ends and reports the one the goods came from."""
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']
    other: StorageLocation = scene['other']

    record = await _sow(real_async_db_session, org.id, template, shelf.id, Decimal('5'))
    await real_async_db_session.commit()

    posted = await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('2'),
        from_location_id=shelf.id,
        to_location_id=other.id,
        reference_type='document',
        reference_id=org.id,
        records=[RecordPostDTO(item_id=record.id, new_quantity=Decimal('3'))],
    )

    assert [part.storage_location_id for part in posted] == [shelf.id]


async def test_the_movement_names_whose_goods_moved_and_who_moved_them(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """A consignor's goods stay named, and the ledger says who moved them.

    The record's own history carries the same hand: the person who posted
    the pass is the one a stock investigation asks for.
    """
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']
    keeper = await shelf_keeper(real_async_db_session, org.id)
    consignor = Partner(
        organization_id=org.id,
        name=f'Consignor {uuid4().hex[:6]}',
        type='SUPPLIER',
    )
    real_async_db_session.add(consignor)
    await real_async_db_session.flush()
    record = await put_on_shelf(
        real_async_db_session,
        keeper,
        template,
        shelf.id,
        Decimal('5'),
        owner_id=consignor.id,
    )
    await real_async_db_session.commit()

    posted = await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('2'),
        from_location_id=shelf.id,
        owner_id=consignor.id,
        reference_type='document',
        reference_id=org.id,
        created_by=keeper.id,
        records=[RecordPostDTO(item_id=record.id, new_quantity=Decimal('3'))],
    )

    assert [part.owner_id for part in posted] == [consignor.id]
    move = (
        await real_async_db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == org.id,
                StockMove.reference_id == org.id,
            )
        )
    ).one()
    assert move.owner_id == consignor.id
    assert move.created_by == keeper.id
    history = (
        await real_async_db_session.scalars(
            select(ItemHistory)
            .where(ItemHistory.item_id == record.id)
            .order_by(ItemHistory.created_at.desc())
        )
    ).first()
    assert history is not None
    assert history.user_id == keeper.id


async def test_a_held_batch_is_refused_unless_the_door_is_scrapping_it(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """A held batch may leave only through a door that says it is disposing.

    Carrying a recalled batch into quarantine is fine; consuming it is not.
    The default is the consuming rule, and the scrap door lifts it by name.
    """
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']

    lot = StockLot(
        organization_id=org.id,
        product_template_id=template.id,
        name=f'RECALLED-{uuid4().hex[:6]}',
        status=LotStatus.HELD.value,
    )
    real_async_db_session.add(lot)
    await real_async_db_session.flush()
    await _sow(
        real_async_db_session,
        org.id,
        template,
        shelf.id,
        Decimal('3'),
        lot_id=lot.id,
    )
    await real_async_db_session.commit()

    with pytest.raises(ValueError, match='cannot be consumed'):
        await post_movement_async(
            real_async_db_session,
            org.id,
            template.id,
            Decimal('1'),
            from_location_id=shelf.id,
            lot_id=lot.id,
            reference_type='document',
            reference_id=org.id,
        )

    posted = await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('1'),
        from_location_id=shelf.id,
        lot_id=lot.id,
        require_active_lot=False,
        reference_type='document',
        reference_id=org.id,
    )
    assert [part.lot_id for part in posted] == [lot.id]


async def test_a_foreign_batch_is_not_read_for_its_status(
    real_async_db_session: AsyncSession, scene: dict[str, Any]
) -> None:
    """Another organization's batch answers like one that is not here."""
    org: Organization = scene['org']
    template: ProductTemplate = scene['template']
    shelf: StorageLocation = scene['shelf']
    other = Organization(
        name=f'Movement foreign {uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'locations', 'categories'],
    )
    real_async_db_session.add(other)
    await real_async_db_session.flush()
    foreign_template = ProductTemplate(
        name=f'Foreign {uuid4().hex[:8]}', organization_id=other.id
    )
    real_async_db_session.add(foreign_template)
    await real_async_db_session.flush()
    foreign_lot = StockLot(
        organization_id=other.id,
        product_template_id=foreign_template.id,
        name='FOREIGN-HELD',
        status=LotStatus.HELD.value,
    )
    real_async_db_session.add(foreign_lot)
    await real_async_db_session.commit()

    posted = await post_movement_async(
        real_async_db_session,
        org.id,
        template.id,
        Decimal('1'),
        from_location_id=shelf.id,
        lot_id=foreign_lot.id,
        reference_type='document',
        reference_id=org.id,
    )
    # The foreign lot's status is not this organization's business: the
    # pass finds no stock of it and writes the movement the caller stated.
    assert [part.lot_id for part in posted] == [foreign_lot.id]
