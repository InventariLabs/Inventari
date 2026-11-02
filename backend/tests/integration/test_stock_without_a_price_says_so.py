"""Stock that arrives without a price, and stock that leaves without a layer.

Two questions of the same kind, and the ledger used to answer them
differently. A surplus off a count, a quantity raised by hand and a
correction with no price all posted a layer at 0.00 — every one of them
diluted the average and understated the assets. A receipt document with no
price on the line posted **nothing**, so the physical stock stopped equalling
the sum of the layers, and nothing looks for that gap.

On the way out, a delivery the layers could not cover consumed what it found
and dropped the rest without a word: no exception, no log line, and after the
outgoing half of the ledger arrived, no layer either. The stock left the
shelf and left no trace in the books.

One policy now covers both directions. An inflow with no price is valued at
the organization's own current rate; if there is no rate to use, the layer is
posted and marked as such — a cost that is unknown says "unknown", never
"zero" and never nothing at all.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer
from app.services.valuation_service import ValuationService


async def _template(db: AsyncSession, org_id: UUID) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name='Priceless Widget',
        sku=f'PW-{uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def _layers(
    db: AsyncSession, org_id: UUID, template_id: UUID, direction: str
) -> list[StockValuationLayer]:
    rows = await db.scalars(
        select(StockValuationLayer)
        .where(
            StockValuationLayer.organization_id == org_id,
            StockValuationLayer.product_template_id == template_id,
            StockValuationLayer.direction == direction,
        )
        .order_by(StockValuationLayer.created_at.asc())
    )
    return list(rows.all())


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnInflowWithoutAPrice:
    async def test_is_valued_at_the_organizations_own_rate(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)

        await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('4.00'), org_id
        )
        # A surplus off a count: nobody said what it cost.
        await ValuationService._record_receipt_async(
            db, template, Decimal('5'), None, org_id
        )

        layers = await _layers(db, org_id, template.id, 'IN')
        assert len(layers) == 2
        assert layers[1].unit_cost == Decimal('4.00')
        assert layers[1].total_value == Decimal('20.00')
        assert layers[1].cost_basis == CostBasis.AVERAGE
        # The average is undisturbed — which is the whole point of not
        # writing a zero into it.
        assert await ValuationService.get_current_valuation_rate_async(
            db, org_id, template.id
        ) == Decimal('4.00')

    async def test_says_unknown_when_there_is_no_rate_to_use(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)

        svl = await ValuationService._record_receipt_async(
            db, template, Decimal('7'), None, org_id
        )

        assert svl is not None
        assert svl.quantity == Decimal('7')
        assert svl.cost_basis == CostBasis.UNKNOWN
        # It is stock, so it counts; it just has no price attached.
        assert svl.remaining_qty == Decimal('7')

    async def test_a_stated_price_is_marked_as_stated(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)

        svl = await ValuationService._record_receipt_async(
            db, template, Decimal('3'), Decimal('2.50'), org_id
        )

        assert svl is not None
        assert svl.cost_basis == CostBasis.STATED


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnOutflowTheLayersCannotCover:
    async def test_is_reported_in_the_log(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)

        await ValuationService._record_receipt_async(
            db, template, Decimal('2'), Decimal('3.00'), org_id
        )

        with caplog.at_level(logging.WARNING):
            await ValuationService._post_delivery_async(
                db, template, Decimal('5'), org_id
            )

        assert any(
            'not covered' in record.message or 'not covered' in record.getMessage()
            for record in caplog.records
        ), [r.getMessage() for r in caplog.records]

    async def test_still_posts_the_outgoing_layer_without_a_rate(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)

        # No receipt at all: the shelf has stock the books never saw.
        await ValuationService._post_delivery_async(
            db, template, Decimal('4'), org_id, reason='DISPOSED'
        )

        out = await _layers(db, org_id, template.id, 'OUT')
        assert len(out) == 1
        assert out[0].quantity == Decimal('4')
        assert out[0].cost_basis == CostBasis.UNKNOWN
        assert out[0].reason == 'DISPOSED'
