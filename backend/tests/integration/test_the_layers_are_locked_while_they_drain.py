"""Two claims on the same stock cannot both be honoured in silence.

Draining the cost layers is a read of ``remaining_qty`` followed by a write
of it, and nothing held the rows in between. Quantities are safe — the stock
paths lock per shelf, on the group's anchor — but the layers are per product, so two outflows of
the same goods from two different shelves read the same layer, each decided
it had enough, and each wrote its own answer back. One of the two writes
survived, and the books then held less consumed than the shelf lost.

The table had nothing to say about it either: a layer could hold a negative
remainder and no constraint objected, so the damage looked like data.

And a reservation asking for the shortest-dated batch could not run at all.
The FEFO branch outer-joins the lot table and the lock was taken over the
whole row set, which Postgres refuses on the nullable side of an outer join.
Nothing reached it in production — the only caller reserves oldest-first —
so the query had never been executed. A reservation is now planned from the
records and takes no lock over that join at all.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.services._stock_reservation import reserve_for_document_async
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.integration


async def _template(db: AsyncSession, org_id, name: str) -> ProductTemplate:
    tpl = ProductTemplate(organization_id=org_id, name=f'{name} {uuid4().hex[:6]}')
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    return tpl


async def _on_shelf(
    db: AsyncSession,
    tpl: ProductTemplate,
    location: StorageLocation,
    quantity: int,
    *,
    lot: StockLot | None = None,
    created_at: datetime | None = None,
) -> Item:
    """A record of *quantity* on the shelf, as old as *created_at*; returns the record."""
    keeper = await shelf_keeper(db, tpl.organization_id)
    lot_id = lot.id if lot is not None else None
    record = await put_on_shelf(db, keeper, tpl, location.id, quantity, lot_id=lot_id)
    if created_at is not None:
        await db.execute(
            update(Item).where(Item.id == record.id).values(created_at=created_at)
        )
    return record


class TestAReservationCanAskForTheShortestDatedBatch:
    """A reservation is planned from the records, in the one removal order.

    The lock that Postgres refused is gone with the quant query it sat on:
    the plan reads the records under the group's anchor, and nothing is
    locked over the lot join.
    """

    async def test_reserving_fefo_runs(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ) -> None:
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _template(db, org_id, 'Yoghurt')
        lot = StockLot(
            organization_id=org_id,
            product_template_id=tpl.id,
            name='L1',
            expiry_date=None,
        )
        db.add(lot)
        await db.flush()
        await _on_shelf(db, tpl, async_test_storage_location, 10, lot=lot)

        result = await reserve_for_document_async(
            db,
            org_id,
            tpl.id,
            async_test_storage_location.id,
            Decimal('4'),
            removal_strategy='FEFO',
            document_id=uuid4(),
        )
        assert result.success
        assert result.unreserved_quantity == Decimal('0')

    async def test_reserving_oldest_first_still_runs(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """The control: the branch that always worked still does."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _template(db, org_id, 'Flour')
        await _on_shelf(db, tpl, async_test_storage_location, 10)

        result = await reserve_for_document_async(
            db,
            org_id,
            tpl.id,
            async_test_storage_location.id,
            Decimal('4'),
            document_id=uuid4(),
        )
        assert result.success

    async def test_a_date_tie_reserves_the_older_record(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """Two lots with the same date are FEFO peers; the older record goes first.

        The record written second is made the older one, so the order the
        rows were written in and the order the rule asks for disagree.
        """
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _template(db, org_id, 'Oats')
        lot_older = StockLot(
            organization_id=org_id,
            product_template_id=tpl.id,
            name='L-old',
            expiry_date=date(2099, 3, 1),
        )
        lot_newer = StockLot(
            organization_id=org_id,
            product_template_id=tpl.id,
            name='L-new',
            expiry_date=date(2099, 3, 1),
        )
        db.add_all([lot_newer, lot_older])
        await db.flush()
        await _on_shelf(
            db,
            tpl,
            async_test_storage_location,
            10,
            lot=lot_newer,
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        await _on_shelf(
            db,
            tpl,
            async_test_storage_location,
            10,
            lot=lot_older,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        result = await reserve_for_document_async(
            db,
            org_id,
            tpl.id,
            async_test_storage_location.id,
            Decimal('4'),
            removal_strategy='FEFO',
            document_id=uuid4(),
        )

        assert result.success
        (locked,) = result.reserved
        assert locked.lot_id == lot_older.id
        assert locked.quantity == Decimal('4')
        assert locked.reservation_id is not None

    async def test_the_reservation_sorts_by_the_shared_removal_rule(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reservation is ordered by the one removal rule every draw uses.

        The reservation side once inlined its own copy of the ordering, and
        the copy drifted. The pin sits on the seam: a reservation plans its
        draw through ``records_in_removal_order``, the same function the
        draw off the records is ordered by.
        """
        from app.services import _stock_draw

        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _template(db, org_id, 'Oats')
        await _on_shelf(db, tpl, async_test_storage_location, 10)

        calls: list[str] = []
        original = _stock_draw.records_in_removal_order

        def _recording(stmt: object, strategy: str) -> object:
            calls.append(strategy)
            return original(stmt, strategy)

        monkeypatch.setattr(_stock_draw, 'records_in_removal_order', _recording)

        result = await reserve_for_document_async(
            db,
            org_id,
            tpl.id,
            async_test_storage_location.id,
            Decimal('4'),
            removal_strategy='FEFO',
            document_id=uuid4(),
        )

        assert result.success
        assert calls == ['FEFO']


class TestALayerCannotHoldLessThanNothing:
    async def test_a_negative_remainder_is_refused_by_the_table(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ) -> None:
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _template(db, org_id, 'Sugar')
        db.add(
            StockValuationLayer(
                organization_id=org_id,
                product_template_id=tpl.id,
                quantity=Decimal('10'),
                remaining_qty=Decimal('-1'),
                unit_cost=Decimal('1'),
                total_value=Decimal('10'),
                direction='IN',
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async def test_an_empty_layer_is_fine(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """The control: nothing left is an ordinary state, below nothing is not."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _template(db, org_id, 'Salt')
        db.add(
            StockValuationLayer(
                organization_id=org_id,
                product_template_id=tpl.id,
                quantity=Decimal('10'),
                remaining_qty=Decimal('0'),
                unit_cost=Decimal('1'),
                total_value=Decimal('10'),
                direction='IN',
            )
        )
        await db.flush()
