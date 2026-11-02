"""A draw is planned from the records of the group, less what their grain holds.

Which batch goes first and how much of it is free used to be read off the
quants: FEFO by the batch's date and then the quant's ``created_at``, the
free part as the quant's quantity less its reserved total. The quants are
gone and the records are the only count, so the draw reads the records —
in one order for every caller, down to the record's id, so two records of
one batch written in the same instant still come out the same way every
time — and the holds from the reservation rows of each (batch, owner).

The plan names each record it draws on and how much, which is one grain
finer than the batch totals the quant primitives returned.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services._stock_draw import RecordDraw, plan_draw_async
from tests.integration._holds import hold_async
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.asyncio


class _Dairy:
    org: Organization
    keeper: UserContextDTO
    shelf_a: StorageLocation
    shelf_b: StorageLocation
    milk: ProductTemplate
    consignor: Partner
    early: StockLot
    late: StockLot
    undated: StockLot
    held: StockLot
    records: dict[str, Item]


@pytest.fixture
async def dairy(real_async_db_session: AsyncSession) -> _Dairy:
    """Milk in four batches and a consignor's, on two shelves.

    Shelf A: 3 of LATE, 2 and 4 of EARLY, 5 of UNDATED, 7 of HELD
    (quarantined), 6 of the consignor's; shelf B: 8 of EARLY.
    """
    db = real_async_db_session
    d = _Dairy()
    d.org = Organization(name=f'Dairy {uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(d.org)
    await db.flush()
    d.keeper = await shelf_keeper(db, d.org.id)
    storage_type = StorageType(
        name='Fridge', type_code=f'FRIDGE_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    d.shelf_a, d.shelf_b = (
        StorageLocation(
            name=name,
            organization_id=d.org.id,
            storage_type_id=storage_type.id,
            created_by=d.keeper.id,
        )
        for name in ('Fridge A', 'Fridge B')
    )
    d.milk = ProductTemplate(
        name='Milk', organization_id=d.org.id, removal_strategy='FEFO'
    )
    d.consignor = Partner(organization_id=d.org.id, name='Consignor', type='SUPPLIER')
    db.add_all([d.shelf_a, d.shelf_b, d.milk, d.consignor])
    await db.flush()
    today = date.today()
    d.early, d.late, d.undated, d.held = (
        StockLot(
            organization_id=d.org.id,
            product_template_id=d.milk.id,
            name=name,
            status=status,
            **dates,
        )
        for name, status, dates in (
            ('EARLY', LotStatus.ACTIVE, {'use_by_date': today + timedelta(days=10)}),
            ('LATE', LotStatus.ACTIVE, {'expiry_date': today + timedelta(days=30)}),
            ('UNDATED', LotStatus.ACTIVE, {}),
            ('HELD', LotStatus.QUARANTINED, {'use_by_date': today + timedelta(days=2)}),
        )
    )
    db.add_all([d.early, d.late, d.undated, d.held])
    await db.flush()

    a, b = d.shelf_a.id, d.shelf_b.id
    d.records = {}
    for key, shelf, quantity, lot, owner in (
        ('late', a, 3, d.late, None),
        ('early_1', a, 2, d.early, None),
        ('early_2', a, 4, d.early, None),
        ('undated', a, 5, d.undated, None),
        ('held', a, 7, d.held, None),
        ('consigned', a, 6, None, d.consignor),
        ('early_b', b, 8, d.early, None),
    ):
        d.records[key] = await put_on_shelf(
            db,
            d.keeper,
            d.milk,
            shelf,
            quantity,
            lot_id=lot.id if lot else None,
            owner_id=owner.id if owner else None,
        )
    await db.commit()
    return d


async def _written_together(db: AsyncSession, *records: Item) -> None:
    """Give *records* one ``created_at``, as if one statement had written them."""
    moment = min(r.created_at for r in records)
    await db.execute(
        update(Item)
        .where(Item.id.in_([r.id for r in records]))
        .values(created_at=moment)
    )
    await db.commit()


def _taken(plan_draws: list[RecordDraw]) -> list[tuple[UUID, Decimal]]:
    return [(draw.record_id, draw.quantity) for draw in plan_draws]


async def test_fefo_takes_the_earliest_date_then_the_oldest_record_then_the_id(
    real_async_db_session: AsyncSession, dairy: _Dairy
) -> None:
    db, r = real_async_db_session, dairy.records
    await _written_together(db, r['early_1'], r['early_2'])
    first, second = sorted([r['early_1'], r['early_2']], key=lambda item: item.id)

    plan = await plan_draw_async(
        db, dairy.org.id, dairy.milk.id, dairy.shelf_a.id, None, strategy='FEFO'
    )

    # Own stock only, the quarantined batch left out; the undated batch last.
    assert _taken(plan.draws) == [
        (first.id, first.quantity),
        (second.id, second.quantity),
        (r['late'].id, Decimal('3')),
        (r['undated'].id, Decimal('5')),
    ]
    assert plan.free == Decimal('14')
    assert plan.on_shelf


async def test_fifo_takes_the_oldest_record_then_the_id(
    real_async_db_session: AsyncSession, dairy: _Dairy
) -> None:
    db, r = real_async_db_session, dairy.records
    own = [r['late'], r['early_1'], r['early_2'], r['undated']]
    await _written_together(db, *own)

    plan = await plan_draw_async(
        db, dairy.org.id, dairy.milk.id, dairy.shelf_a.id, None, strategy='FIFO'
    )

    assert [draw.record_id for draw in plan.draws] == sorted(
        record.id for record in own
    )


async def test_a_hold_leaves_its_batch_short_and_the_draw_moves_on(
    real_async_db_session: AsyncSession, dairy: _Dairy
) -> None:
    db, r = real_async_db_session, dairy.records
    early_on_a = await db.scalar(
        select(ShelfRow).where(
            ShelfRow.lot_id == dairy.early.id,
            ShelfRow.storage_location_id == dairy.shelf_a.id,
        )
    )
    assert early_on_a is not None
    await hold_async(db, early_on_a, Decimal('5'))
    await db.commit()

    plan = await plan_draw_async(
        db, dairy.org.id, dairy.milk.id, dairy.shelf_a.id, Decimal('4'), strategy='FEFO'
    )

    # EARLY holds 6 on shelf A and 5 of it are promised: 1 is free, and it
    # comes off the batch's first record; the rest comes from LATE.
    assert _taken(plan.draws) == [
        (r['early_1'].id, Decimal('1')),
        (r['late'].id, Decimal('3')),
    ]
    assert [(d.lot_id, d.owner_id, d.storage_location_id) for d in plan.draws] == [
        (dairy.early.id, None, dairy.shelf_a.id),
        (dairy.late.id, None, dairy.shelf_a.id),
    ]
    assert plan.free == Decimal('9')


async def test_the_owner_decides_whose_goods_are_drawn(
    real_async_db_session: AsyncSession, dairy: _Dairy
) -> None:
    db, r = real_async_db_session, dairy.records
    org, milk, shelf = dairy.org.id, dairy.milk.id, dairy.shelf_a.id

    consigned = await plan_draw_async(
        db, org, milk, shelf, None, strategy='FEFO', owner_id=dairy.consignor.id
    )
    everyone = await plan_draw_async(
        db, org, milk, shelf, None, strategy='FEFO', any_owner=True
    )

    assert _taken(consigned.draws) == [(r['consigned'].id, Decimal('6'))]
    # Without a batch the consignor's goods have no date, and sink with the
    # undated batch to the end.
    assert {d.record_id for d in everyone.draws[-2:]} == {
        r['undated'].id,
        r['consigned'].id,
    }
    assert everyone.free == Decimal('20')


async def test_every_shelf_when_none_is_named(
    real_async_db_session: AsyncSession, dairy: _Dairy
) -> None:
    db, r = real_async_db_session, dairy.records

    plan = await plan_draw_async(
        db, dairy.org.id, dairy.milk.id, None, Decimal('9'), strategy='FEFO'
    )

    assert {d.record_id for d in plan.draws} == {
        r['early_1'].id,
        r['early_2'].id,
        r['early_b'].id,
    }
    assert sum(d.quantity for d in plan.draws) == Decimal('9')
    assert plan.free == Decimal('22')


async def test_nothing_on_the_shelf_is_told_apart_from_nothing_free(
    real_async_db_session: AsyncSession, dairy: _Dairy
) -> None:
    db = real_async_db_session
    held_only = ProductTemplate(name='Cream', organization_id=dairy.org.id)
    nothing = ProductTemplate(name='Butter', organization_id=dairy.org.id)
    db.add_all([held_only, nothing])
    await db.flush()
    quarantined = StockLot(
        organization_id=dairy.org.id,
        product_template_id=held_only.id,
        name='C-1',
        status=LotStatus.QUARANTINED,
    )
    db.add(quarantined)
    await db.flush()
    await put_on_shelf(
        db, dairy.keeper, held_only, dairy.shelf_a.id, 2, lot_id=quarantined.id
    )
    await db.commit()

    held = await plan_draw_async(
        db, dairy.org.id, held_only.id, dairy.shelf_a.id, Decimal('1'), strategy='FIFO'
    )
    empty = await plan_draw_async(
        db, dairy.org.id, nothing.id, dairy.shelf_a.id, Decimal('1'), strategy='FIFO'
    )

    assert (held.draws, held.free, held.on_shelf) == ([], Decimal('0'), True)
    assert (empty.draws, empty.free, empty.on_shelf) == ([], Decimal('0'), False)


async def test_among_shelves_takes_only_the_named_shelves_in_removal_order(
    real_async_db_session: AsyncSession, dairy: _Dairy
) -> None:
    """A zone's draw is the shelves below it, read as one list in one order.

    With every shelf named, the batch that is earliest on either shelf comes
    first, whichever shelf it stands on; with only shelf A named, shelf B's
    record is not a candidate at all.
    """
    db, r = real_async_db_session, dairy.records
    org, milk = dairy.org.id, dairy.milk.id

    only_a = await plan_draw_async(
        db,
        org,
        milk,
        None,
        None,
        strategy='FEFO',
        among_shelves=[dairy.shelf_a.id],
    )
    both = await plan_draw_async(
        db,
        org,
        milk,
        None,
        None,
        strategy='FEFO',
        among_shelves=[dairy.shelf_a.id, dairy.shelf_b.id],
    )

    assert {d.storage_location_id for d in only_a.draws} == {dairy.shelf_a.id}
    assert only_a.free == Decimal('14')
    assert r['early_b'].id not in {d.record_id for d in only_a.draws}
    assert {d.record_id for d in both.draws[:3]} == {
        r['early_1'].id,
        r['early_2'].id,
        r['early_b'].id,
    }
    assert [d.record_id for d in both.draws[-2:]] == [
        r['late'].id,
        r['undated'].id,
    ]
    assert both.free == Decimal('22')
