"""The reads that used to take numbers from the quant table take them from the records.

Five places read rows of the quant table directly — the batch detail and the
batch list's on-hand column, the shelf occupancy behind a location delete, the
reservation guard inside deleting a record, and the CLI's reservation check.
They were moved onto the records and the reservation rows before the table
was dropped.

With the table gone there is no mirror left to tamper with, so these tests no
longer prove that a read ignores it; they pin what each read answers from the
records and the reservation rows.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.public_api import core_api
from app.models.item import Item
from app.models.stock_reservation import StockReservation

from ._core_api_helpers import make_template, make_user_context
from ._holds import past_the_hold_guard_async
from ._shelf import put_on_shelf

pytestmark = pytest.mark.integration


class TestBatchDetailReadsTheRecords:
    """``get_lot_detail_async`` sums the records."""

    async def test_the_batch_detail_counts_the_records(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ) -> None:
        from app.services._stock_lot_ops import get_lot_detail_async

        db = real_async_db_session
        org_id = async_test_household.id
        template = await db.run_sync(lambda s: make_template(s, org_id))
        lot_id = await core_api.stock.get_or_create_lot_async(
            db=db,
            organization_id=org_id,
            product_template_id=template.id,
            name='LOT-T12',
        )
        await put_on_shelf(
            db,
            async_test_user,
            template,
            async_test_storage_location.id,
            Decimal('7'),
            lot_id=lot_id,
        )
        await db.commit()

        detail = await get_lot_detail_async(db, org_id, lot_id)

        assert detail is not None, 'the batch the test just put on the shelf'
        assert detail.on_hand == Decimal('7'), detail.on_hand
        place = next(
            p
            for p in detail.locations
            if p.location_id == async_test_storage_location.id
        )
        assert place.quantity == Decimal('7')
        assert place.reserved_quantity == Decimal('0')


class TestBatchListReadsTheRecords:
    """``list_lot_rows_async`` sums the records, so the list and the detail agree.

    The batch list's on-hand column is what a recall day reads first; the
    batch's own screen is where it goes next. Two sources for one number
    would show two numbers the moment they drift apart.
    """

    async def test_the_batch_list_adds_up_the_records_of_every_shelf(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
        async_test_storage_type,
        async_test_user,
    ) -> None:
        from app.models.storage_location import StorageLocation
        from app.services._stock_lot_ops import (
            get_lot_detail_async,
            list_lot_rows_async,
        )

        db = real_async_db_session
        org_id = async_test_household.id
        template = await db.run_sync(lambda s: make_template(s, org_id))
        pantry = StorageLocation(
            organization_id=org_id,
            created_by=async_test_user.id,
            storage_type_id=async_test_storage_type.id,
            name='Pantry',
        )
        db.add(pantry)
        await db.flush()
        lot_id = await core_api.stock.get_or_create_lot_async(
            db=db,
            organization_id=org_id,
            product_template_id=template.id,
            name='LOT-LIST',
        )
        # Two shelves, so the list has two groups of the batch to add up.
        for location_id, quantity in (
            (async_test_storage_location.id, Decimal('4')),
            (pantry.id, Decimal('3')),
        ):
            await put_on_shelf(
                db, async_test_user, template, location_id, quantity, lot_id=lot_id
            )
        await db.commit()

        rows, _ = await list_lot_rows_async(db, org_id, product_template_id=template.id)
        detail = await get_lot_detail_async(db, org_id, lot_id)

        row = next(r for r in rows if r.id == lot_id)
        assert row.on_hand == Decimal('7'), row.on_hand
        assert detail is not None
        assert row.on_hand == detail.on_hand


class TestTheRecordDeleteGuardReadsTheReservationRows:
    """Deleting a record asks for a release when the ROWS hold stock.

    The guard decides whether the unbacked part of the holds has to go
    before the record is zeroed. It used to read the quant's running total
    of reservations while a release acts on the reservation rows; it reads
    the rows now.
    """

    async def test_the_rows_holding_the_shelf_are_seen(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
        async_test_user,
        monkeypatch,
    ) -> None:
        from app.services import _stock_reservation
        from app.services.items import delete_item

        db = real_async_db_session
        org_id = async_test_household.id
        template = await db.run_sync(lambda s: make_template(s, org_id))
        item = await put_on_shelf(
            db,
            async_test_user,
            template,
            async_test_storage_location.id,
            Decimal('5'),
        )
        await core_api.stock.reserve_for_document_async(
            db,
            organization_id=org_id,
            product_template_id=template.id,
            location_id=async_test_storage_location.id,
            needed_qty=Decimal('3'),
            document_id=uuid.uuid4(),
        )
        await db.commit()

        rows = (
            await db.scalars(
                select(StockReservation).where(
                    StockReservation.organization_id == org_id
                )
            )
        ).all()
        assert rows, 'the test needs a reservation row for the guard to see'

        seen: list[Decimal] = []
        release = _stock_reservation.release_unbacked_async

        # Recorded, then carried out: a release that did nothing would leave
        # the holds standing on a record taken to zero, which the bridge
        # refuses — the guard's question is what this test asks about.
        async def recorder(*args, **kwargs) -> Decimal:
            seen.append(kwargs['leaving_quantity'])
            released: Decimal = await release(*args, **kwargs)
            return released

        monkeypatch.setattr(_stock_reservation, 'release_unbacked_async', recorder)

        user_ctx = make_user_context(org_id, async_test_user.id)
        await delete_item(db, item, user_ctx, reason='DAMAGED')

        assert seen == [Decimal('5')], (
            'the guard did not read the reservation rows: it never asked for a '
            f'release (seen: {seen})'
        )


class TestShelfOccupancyReadsTheRecords:
    """``locations_holding_stock_async`` counts records."""

    async def test_a_shelf_whose_record_is_there_counts(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ) -> None:
        from app.services.storage._queries import locations_holding_stock_async

        db = real_async_db_session
        org_id = async_test_household.id
        template = await db.run_sync(lambda s: make_template(s, org_id))
        await put_on_shelf(
            db,
            async_test_user,
            template,
            async_test_storage_location.id,
            Decimal('3'),
        )
        await db.commit()

        holding = await locations_holding_stock_async(
            db, org_id, [async_test_storage_location.id]
        )

        assert holding == {async_test_storage_location.id}


class TestTheCliCheckReadsRecordsAndRows:
    """``db check-reservations`` compares the shelf with the promises on it."""

    async def test_a_shelf_the_promises_exceed_is_reported(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ) -> None:
        from app.cli.commands_db import reservation_disagreements

        db = real_async_db_session
        org_id = async_test_household.id
        template = await db.run_sync(lambda s: make_template(s, org_id))
        await put_on_shelf(
            db,
            async_test_user,
            template,
            async_test_storage_location.id,
            Decimal('5'),
        )
        await core_api.stock.reserve_for_document_async(
            db,
            organization_id=org_id,
            product_template_id=template.id,
            location_id=async_test_storage_location.id,
            needed_qty=Decimal('3'),
            document_id=uuid.uuid4(),
        )
        await db.commit()

        carried = await db.run_sync(reservation_disagreements)
        assert carried == [], (
            'a shelf carrying 5 with 3 promised on it is not a disagreement, and '
            f'the check must not invent one ({carried})'
        )

        # The shelf loses the stock behind the promises: the records say 2,
        # the rows still promise 3. The database refuses such a grain at
        # commit now, so this is the shape an instance older than that guard
        # holds.
        item = (
            await db.scalars(
                select(Item).where(
                    Item.organization_id == org_id,
                    Item.template_id == template.id,
                )
            )
        ).one()
        async with past_the_hold_guard_async(db):
            item.quantity = Decimal('2')
        await db.commit()

        found = await db.run_sync(reservation_disagreements)

        assert [
            (r.product_template_id, r.reserved_quantity, r.quantity) for r in found
        ] == [(template.id, Decimal('3'), Decimal('2'))], (
            f'the records carry 2 while the rows promise 3 ({found})'
        )
