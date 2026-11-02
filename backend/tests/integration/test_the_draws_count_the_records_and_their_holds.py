"""Every draw counts what is free from the records and the reservation rows.

A draw used to ask the quants: which batch goes first, and how much of it
is free — the quant's quantity less its ``reserved_quantity``. The records
are the count now, and the reservation rows are the holds, so the draws that
choose what to take — a draw off the records, a reservation, the release of
what no stock covers any more and the picking suggestion — ask them. The
draw off the records is measured through its doors: a dispatch
(``test_documents_fefo.py``) and a production run
(``test_a_run_takes_its_ingredients_off_their_own_records.py``).

The shelf here holds batch EARLY first in line by its date, and promised
whole by a reservation row written by hand. The records and the rows say it
is held. Every draw has to pass it by.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.testing import ShelfRow
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services._stock_quant_query import find_best_pick_group_for_picking_async
from app.services._stock_reservation import (
    release_unbacked_async,
    reserve_for_document_async,
)
from tests.integration._holds import hold_async
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.asyncio


class _Shelf:
    org: Organization
    keeper: UserContextDTO
    shelf: StorageLocation
    tea: ProductTemplate
    early: StockLot
    late: StockLot


@pytest.fixture
async def shelf(real_async_db_session: AsyncSession) -> _Shelf:
    """Tea in two batches, 5 of each; EARLY promised whole by a row written by hand."""
    db = real_async_db_session
    s = _Shelf()
    s.org = Organization(name=f'Tea {uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(s.org)
    await db.flush()
    s.keeper = await shelf_keeper(db, s.org.id)
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    s.shelf = StorageLocation(
        name='Tea shelf',
        organization_id=s.org.id,
        storage_type_id=storage_type.id,
        created_by=s.keeper.id,
    )
    s.tea = ProductTemplate(
        name='Tea', organization_id=s.org.id, removal_strategy='FEFO'
    )
    db.add_all([s.shelf, s.tea])
    await db.flush()
    today = date.today()
    s.early, s.late = (
        StockLot(
            organization_id=s.org.id,
            product_template_id=s.tea.id,
            name=name,
            expiry_date=today + timedelta(days=days),
        )
        for name, days in (('EARLY', 10), ('LATE', 90))
    )
    db.add_all([s.early, s.late])
    await db.flush()
    for lot in (s.early, s.late):
        await put_on_shelf(db, s.keeper, s.tea, s.shelf.id, 5, lot_id=lot.id)
    early = await db.scalar(select(ShelfRow).where(ShelfRow.lot_id == s.early.id))
    assert early is not None
    await hold_async(db, early, Decimal('5'))
    await db.commit()
    return s


async def test_a_reservation_passes_the_held_batch_by(
    real_async_db_session: AsyncSession, shelf: _Shelf
) -> None:
    result = await reserve_for_document_async(
        real_async_db_session,
        shelf.org.id,
        shelf.tea.id,
        shelf.shelf.id,
        Decimal('3'),
        removal_strategy='FEFO',
        document_id=uuid4(),
    )

    assert result.success
    (locked,) = result.reserved
    assert locked.lot_id == shelf.late.id
    assert locked.quantity == Decimal('3')
    assert locked.reservation_id is not None


async def test_the_picking_suggestion_passes_the_held_batch_by(
    real_async_db_session: AsyncSession, shelf: _Shelf
) -> None:
    suggested = await find_best_pick_group_for_picking_async(
        real_async_db_session, shelf.org.id, shelf.tea.id, shelf.shelf.id
    )

    assert suggested is not None
    assert suggested.lot_id == shelf.late.id


async def test_a_document_plans_the_batch_its_own_hold_covers(
    real_async_db_session: AsyncSession, shelf: _Shelf
) -> None:
    """The row holding EARLY is not someone else's when its document asks."""
    db = real_async_db_session
    holding = await db.scalar(
        select(StockReservation).where(StockReservation.organization_id == shelf.org.id)
    )
    assert holding is not None

    suggested = await find_best_pick_group_for_picking_async(
        db,
        shelf.org.id,
        shelf.tea.id,
        shelf.shelf.id,
        except_document_id=holding.document_id,
    )

    assert suggested is not None
    assert suggested.lot_id == shelf.early.id


async def test_stock_leaving_releases_the_hold_its_records_no_longer_cover(
    real_async_db_session: AsyncSession, shelf: _Shelf
) -> None:
    db = real_async_db_session

    released = await release_unbacked_async(
        db, shelf.org.id, shelf.tea.id, shelf.shelf.id, Decimal('5')
    )

    # EARLY's five records are leaving and the row holding them has nothing
    # behind it any more; LATE holds nothing, so there is nothing to keep.
    assert released == Decimal('5')
    held = await db.scalar(
        select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
            StockReservation.organization_id == shelf.org.id
        )
    )
    assert held == 0


async def test_a_draw_on_every_shelf_locks_a_shelf_its_first_lock_missed(
    real_async_db_session: AsyncSession,
    shelf: _Shelf,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shelf the product's lock did not cover is locked by name before the draw.

    Every shelf of a product locks the anchors there are when the lock is
    taken; a shelf whose first stock is committed while the lock waits has
    one it never saw, and the plan reads that stock all the same. The first
    lock here is made to have missed the tea shelf, as it would that one.
    """
    from app.services import _stock_quant_ops

    calls: list[list[tuple[object, object]]] = []
    real_lock = _stock_quant_ops.lock_stock_async

    async def _first_lock_misses_the_shelf(db, organization_id, *, keys=(), **kw):
        calls.append(list(keys))
        locked = await real_lock(db, organization_id, keys=keys, **kw)
        return set() if len(calls) == 1 else locked

    monkeypatch.setattr(
        _stock_quant_ops, 'lock_stock_async', _first_lock_misses_the_shelf
    )

    result = await reserve_for_document_async(
        real_async_db_session,
        shelf.org.id,
        shelf.tea.id,
        None,
        Decimal('3'),
        removal_strategy='FEFO',
        document_id=uuid4(),
    )

    (locked,) = result.reserved
    assert locked.lot_id == shelf.late.id
    assert locked.quantity == Decimal('3')
    assert locked.reservation_id is not None
    assert calls == [[(shelf.tea.id, None)], [(shelf.tea.id, shelf.shelf.id)]]
