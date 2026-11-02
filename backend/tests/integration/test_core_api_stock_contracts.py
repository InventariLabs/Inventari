"""
Contract tests for CoreStockAPI (app.core.public_api.core_api.stock).

These tests pin down the SHAPE of the lot methods. The quant primitives
whose contracts stood here went with the quant table; the draw that
replaced them (``take_from_the_records_async``) and the movement pass
(``post_movement_async``) are tested beside their own behaviour.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._core_api_helpers import make_template


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreStockGetOrCreateLotContract:
    """`get_or_create_lot_async` returns UUID of StockLot."""

    async def test_get_or_create_lot_creates_new_lot(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )

        result = await core_api.stock.get_or_create_lot_async(
            db=db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            name='LOT-001',
        )
        assert isinstance(result, type(uuid4()))

    async def test_get_or_create_lot_is_idempotent(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await db.run_sync(
            lambda s: make_template(s, async_test_household.id)
        )

        first = await core_api.stock.get_or_create_lot_async(
            db=db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            name='LOT-IDEMPOTENT',
        )
        second = await core_api.stock.get_or_create_lot_async(
            db=db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            name='LOT-IDEMPOTENT',
        )
        assert first == second
