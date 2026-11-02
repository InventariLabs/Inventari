"""Deleting one record must not hand somebody else's reserved stock away.

A group of stock is shared: it holds the stock of one product at one place,
no matter how many item records stand behind it. Reservations hang off the
group and belong to documents, not to records. Deleting a record used to
release ``old_quantity`` worth of them regardless -- so scrapping one bottle
of six released the hold a picking document had on the other five, and left
the document's own StockReservation rows behind claiming stock that was no
longer protected.

The rule the sibling case already established for decrements applies here
too: what remains after stock leaves still covers every reservation, so
there is nothing to release. Only when the record being deleted is the last
stock behind the group does a hold genuinely lose its backing, and then only
the uncovered part goes. The rows are the hold (the quant that kept a running
total beside them is gone), and the records' view counts them as the group's
``reserved_quantity``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.items._lifecycle import delete_item
from tests.integration._shelf import put_on_shelf, reserve_for_an_order

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

HELD_BY_A_DOCUMENT = Decimal('4')


class _Shelf:
    def __init__(self) -> None:
        self.user: User
        self.context: object
        self.template_id: uuid.UUID
        self.location_id: uuid.UUID
        self.doomed: Item
        self.survivor: Item | None = None


async def _shelf(db: AsyncSession, *, records: list[Decimal]) -> _Shelf:
    """One product at one place, its stock split across ``records``."""
    fixture = _Shelf()

    org = Organization(
        name=f'Holds {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()

    fixture.user = await ModuleTestHelper.create_user_async(
        db, org, email=f'holds_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid.uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=fixture.user.id,
    )
    template = ProductTemplate(
        organization_id=org.id, name='Olive oil', sku=f'OO-{uuid.uuid4().hex[:8]}'
    )
    db.add_all([location, template])
    await db.flush()

    items = [
        await put_on_shelf(db, fixture.user, template, location.id, quantity)
        for quantity in records
    ]
    # A picking document's claim, as the reserving path records it.
    await reserve_for_an_order(db, template, location.id, HELD_BY_A_DOCUMENT)
    await db.flush()
    fixture.template_id, fixture.location_id = template.id, location.id

    fixture.doomed = items[0]
    fixture.survivor = items[1] if len(items) > 1 else None
    return fixture


async def _group(db: AsyncSession, shelf: _Shelf) -> ShelfRow | None:
    """The shelf's group as the records' view has it; none once it is empty."""
    return await db.scalar(
        select(ShelfRow).where(
            ShelfRow.product_template_id == shelf.template_id,
            ShelfRow.storage_location_id == shelf.location_id,
        )
    )


async def _reserved_and_rows(
    db: AsyncSession, shelf: _Shelf
) -> tuple[Decimal, Decimal]:
    """What the view says is held, and what the rows behind it add up to."""
    group = await _group(db, shelf)
    held = group.reserved_quantity if group is not None else Decimal('0')
    rows = await db.scalar(
        select(func.coalesce(func.sum(StockReservation.quantity), 0))
        .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
        .where(
            StockAnchor.product_template_id == shelf.template_id,
            StockAnchor.storage_location_id == shelf.location_id,
        )
    )
    return held, Decimal(str(rows))


class TestAnotherRecordStillBacksTheHold:
    async def test_the_hold_survives_the_deletion(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        shelf = await _shelf(db, records=[Decimal('6'), Decimal('4')])

        await delete_item(db, shelf.doomed, shelf.user)
        await db.flush()

        held, rows = await _reserved_and_rows(db, shelf)
        assert held == HELD_BY_A_DOCUMENT
        assert rows == HELD_BY_A_DOCUMENT

    async def test_the_stock_that_left_is_the_stock_that_was_deleted(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        shelf = await _shelf(db, records=[Decimal('6'), Decimal('4')])

        await delete_item(db, shelf.doomed, shelf.user)
        await db.flush()

        group = await _group(db, shelf)
        assert group is not None
        assert group.quantity == Decimal('4')


class TestNothingIsLeftToBackTheHold:
    async def test_the_record_is_still_deletable(
        self, real_async_db_session: AsyncSession
    ):
        """The reason the release was there in the first place."""
        db = real_async_db_session
        shelf = await _shelf(db, records=[Decimal('10')])

        await delete_item(db, shelf.doomed, shelf.user)
        await db.flush()

        assert shelf.doomed.is_deleted is True

    async def test_the_last_record_takes_the_hold_it_backed_with_it(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        shelf = await _shelf(db, records=[Decimal('10')])

        await delete_item(db, shelf.doomed, shelf.user)
        await db.flush()

        held, rows = await _reserved_and_rows(db, shelf)
        assert (held, rows) == (Decimal('0'), Decimal('0')), (
            'no stock is left behind the hold, so the hold is released'
        )
