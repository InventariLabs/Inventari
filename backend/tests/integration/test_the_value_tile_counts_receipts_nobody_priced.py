"""A stock value that leaves a receipt out says how many it left out.

A receipt posted with no price, of a product the organization has no rate
for, puts its goods on the shelf and nothing in the total: the layer is
marked ``unknown``. The tile showed the sum with the same confidence as
before, so a month of unpriced deliveries read as a smaller warehouse.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_template import ProductTemplate
from app.services.analytics.overview import get_overview_async
from app.services.valuation_service import ValuationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _template(db: AsyncSession, org_id, sku: str) -> ProductTemplate:
    template = ProductTemplate(organization_id=org_id, name=f'Goods {sku}', sku=sku)
    db.add(template)
    await db.flush()
    return template


class TestTheTileCountsWhatItCouldNotValue:
    async def test_an_unpriced_receipt_is_counted_beside_the_value(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org = async_test_household
        org.enabled_modules = list(org.enabled_modules or []) + ['warehouse']
        await db.flush()

        priced = await _template(db, org.id, 'P-1')
        unpriced = await _template(db, org.id, 'U-1')
        await ValuationService._record_receipt_async(
            db, priced, Decimal('4'), Decimal('7.50'), org.id
        )
        await ValuationService._record_receipt_async(
            db, unpriced, Decimal('3'), None, org.id
        )
        await db.flush()

        overview = await get_overview_async(db, org.id)

        assert overview.total_value == pytest.approx(30.0)
        assert overview.unvalued_stock_count == 1

    async def test_a_warehouse_that_priced_everything_counts_nothing(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org = async_test_household
        org.enabled_modules = list(org.enabled_modules or []) + ['warehouse']
        await db.flush()
        priced = await _template(db, org.id, 'P-2')
        await ValuationService._record_receipt_async(
            db, priced, Decimal('2'), Decimal('5'), org.id
        )
        await db.flush()

        overview = await get_overview_async(db, org.id)

        assert overview.unvalued_stock_count == 0
