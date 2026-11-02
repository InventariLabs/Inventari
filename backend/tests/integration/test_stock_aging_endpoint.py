"""End-to-end integration test for stock aging.

Exercises the SQL aggregation: StockMove rows for a product with
different created_at ages are bucketed correctly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.core.public_api import core_api
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove


@pytest.mark.integration
@pytest.mark.asyncio
class TestStockAgingEndToEnd:
    async def test_buckets_receipts_by_age(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Aging Test',
            sku=f'SKU-AGE-{uuid.uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()

        as_of = datetime(2026, 6, 23, tzinfo=UTC)
        receipts = [
            (as_of - timedelta(days=10), Decimal('5')),
            (as_of - timedelta(days=45), Decimal('3')),
            (as_of - timedelta(days=120), Decimal('7')),
        ]
        for received_at, qty in receipts:
            move = await core_api.stock_moves.create_async(
                db,
                organization_id=async_test_household.id,
                product_template_id=template.id,
                to_location_id=async_test_storage_location.id,
                quantity=qty,
            )
            # Both stamps move: completed_at is the business date the
            # aging cuts on, created_at its fallback.
            await db.execute(
                update(StockMove)
                .where(StockMove.id == move.id)
                .values(created_at=received_at, completed_at=received_at)
            )
        await db.commit()

        buckets = await core_api.stock_moves.aggregate_aging_buckets_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            as_of=as_of,
        )

        by_label = {b.label: b for b in buckets}
        assert by_label['0-30'].quantity == Decimal('5')
        assert by_label['31-60'].quantity == Decimal('3')
        assert by_label['91-180'].quantity == Decimal('7')
        assert by_label['61-90'].quantity == Decimal('0')
        assert by_label['180+'].quantity == Decimal('0')

    async def test_internal_transfers_excluded(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Transfers Test',
            sku=f'SKU-TRF-{uuid.uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()

        await core_api.stock_moves.create_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            from_location_id=async_test_storage_location.id,
            to_location_id=async_test_storage_location.id,
            quantity=Decimal('99'),
        )
        await db.commit()

        buckets = await core_api.stock_moves.aggregate_aging_buckets_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
        )
        assert all(b.quantity == Decimal('0') for b in buckets)
