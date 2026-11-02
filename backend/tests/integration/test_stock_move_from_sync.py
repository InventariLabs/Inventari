"""Tests for StockMove creation wired into _post_the_change_async.

Every change to Item.quantity on a template-linked item should produce
a corresponding StockMove record.  This is the foundation for analytics
on movement history (FIFO/FEFO, aging, traceability).

Contract:
    - increment: StockMove(to=item.storage_location_id, quantity=delta)
    - decrement: StockMove(from=item.storage_location_id, quantity=abs_delta)
    - no-op (delta=0): no StockMove
    - a record that predates its card (`template_id` NULL) is adopted into one
      and the move is written, in every organization — each keeps the register
    - reference_type='item', reference_id=item.id
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.item import Item
from app.models.stock_move import StockMove
from app.services.items._date_meta import merge_legacy_date_into_meta
from app.services.items._stock_quant import apply_quantity_change_async
from tests.integration._shelf import anchor_pending_records

from ._core_api_helpers import make_template


def _make_item(
    db_session,
    org_id,
    user_id,
    location_id,
    category_id,
    template,
    quantity: Decimal = Decimal('10'),
) -> Item:
    item = Item(
        organization_id=org_id,
        storage_location_id=location_id,
        category_id=category_id,
        template_id=template.id,
        name='Tracked Item',
        quantity=quantity,
        expiry_date=date.today() + timedelta(days=30),
    )
    item.meta_data = merge_legacy_date_into_meta(
        item.meta_data, 'freeze_date', date.today()
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.flush()
    return item


async def _moves_for_item(session, org_id, item_id):
    return list(
        (
            await session.scalars(
                select(StockMove)
                .where(
                    StockMove.organization_id == org_id,
                    StockMove.reference_type == 'item',
                    StockMove.reference_id == item_id,
                )
                .order_by(StockMove.created_at)
            )
        ).all()
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestSyncStockQuantCreatesMove:
    """_post_the_change_async must produce StockMove for every delta."""

    async def test_increment_creates_inbound_move(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_category,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )
        item = await db.run_sync(
            lambda s: _make_item(
                s,
                async_test_household.id,
                async_test_user.id,
                async_test_storage_location.id,
                async_test_category.id,
                template,
                quantity=Decimal('0'),
            )
        )
        await db.commit()

        await apply_quantity_change_async(db, item, Decimal('7'))
        await db.commit()

        moves = await _moves_for_item(db, async_test_household.id, item.id)
        assert len(moves) == 1
        m = moves[0]
        assert m.from_location_id is None
        assert m.to_location_id == async_test_storage_location.id
        assert m.quantity == Decimal('7')
        assert m.product_template_id == template.id
        assert m.reference_type == 'item'
        assert m.reference_id == item.id

    async def test_decrement_creates_outbound_move(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_category,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )
        item = await db.run_sync(
            lambda s: _make_item(
                s,
                async_test_household.id,
                async_test_user.id,
                async_test_storage_location.id,
                async_test_category.id,
                template,
                quantity=Decimal('10'),
            )
        )
        await db.commit()

        await apply_quantity_change_async(db, item, Decimal('3'))
        await db.commit()

        moves = await _moves_for_item(db, async_test_household.id, item.id)
        assert len(moves) == 1
        m = moves[0]
        assert m.from_location_id == async_test_storage_location.id
        assert m.to_location_id is None
        assert m.quantity == Decimal('7')

    async def test_no_op_creates_no_move(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_category,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )
        item = await db.run_sync(
            lambda s: _make_item(
                s,
                async_test_household.id,
                async_test_user.id,
                async_test_storage_location.id,
                async_test_category.id,
                template,
                quantity=Decimal('5'),
            )
        )
        await db.commit()

        await apply_quantity_change_async(db, item, Decimal('5'))
        await db.commit()

        moves = await _moves_for_item(db, async_test_household.id, item.id)
        assert moves == []

    async def test_a_cardless_record_is_adopted_and_creates_a_move(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_category,
        async_test_storage_location,
    ):
        """A record that predates its card joins the ledger; it is not skipped.

        This test used to pin the opposite — "no template, no StockMove
        target" — and that was the defect: the number on the record moved
        while the shelf it stood on stood still and the register stayed
        empty.
        """
        db = real_async_db_session

        def _make(db_session):
            item = Item(
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                category_id=async_test_category.id,
                template_id=None,
                name='No Template',
                quantity=Decimal('0'),
                expiry_date=date.today() + timedelta(days=10),
            )
            item.meta_data = merge_legacy_date_into_meta(
                item.meta_data, 'freeze_date', date.today()
            )
            db_session.add(item)
            db_session.flush()
            return item

        item = await db.run_sync(_make)
        await db.commit()

        await apply_quantity_change_async(db, item, Decimal('5'))
        await db.commit()

        moves = await _moves_for_item(db, async_test_household.id, item.id)
        assert len(moves) == 1
        assert moves[0].quantity == Decimal('5')
        assert moves[0].to_location_id == async_test_storage_location.id
        assert moves[0].from_location_id is None
        assert item.template_id is not None, (
            'the record is still outside the ledger: no card, so nothing the '
            'move was written for'
        )

    async def test_a_cardless_record_in_an_organization_without_register_modules_moves_too(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_category,
        async_test_storage_location,
    ):
        """No stock module is enabled, and the register is kept all the same.

        It used to be left exactly as it was — no card minted, no movement,
        ``Item.quantity`` its only truth. Now every organization
        keeps the register, so the record adopts its card and the change is
        a movement, as in an organization with the modules.
        """
        db = real_async_db_session
        async_test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
        ]
        await db.commit()

        def _make(db_session):
            item = Item(
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                category_id=async_test_category.id,
                template_id=None,
                name='No Template',
                quantity=Decimal('0'),
                expiry_date=date.today() + timedelta(days=10),
            )
            item.meta_data = merge_legacy_date_into_meta(
                item.meta_data, 'freeze_date', date.today()
            )
            db_session.add(item)
            db_session.flush()
            return item

        item = await db.run_sync(_make)
        await db.commit()

        await apply_quantity_change_async(db, item, Decimal('5'))
        await db.commit()

        moves = await _moves_for_item(db, async_test_household.id, item.id)
        assert [m.quantity for m in moves] == [Decimal('5')]
        assert item.template_id is not None
        assert item.quantity == Decimal('5')
