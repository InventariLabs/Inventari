"""The layer-average rate is rounded to the precision the column actually has.

``unit_cost`` is ``Numeric(12, 4)`` and the docstring on the receipt path
promises that a cost per gram keeps its decimals. The rate was rounded to two
anyway, so a spice at 0.0234 per gram came back as 0.02 — fifteen per cent of
it gone — and anything under half a grosz per unit came back as zero, which is
the one answer the cost basis exists to keep apart from "nobody said".

The damage does not stop at the number returned: an unpriced receipt is valued
at this rate, so the truncation is written into the next layer and every layer
that inherits from it.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer
from app.services.valuation_service import ValuationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _template_with_receipt(
    db: AsyncSession, org_id, quantity: Decimal, unit_cost: Decimal
) -> ProductTemplate:
    """A template this organization has taken one priced delivery of."""
    template = ProductTemplate(
        organization_id=org_id,
        name='Ground spice',
        sku=f'GS-{uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)

    await ValuationService._record_receipt_async(
        db, template, quantity, unit_cost, org_id
    )
    await db.flush()
    return template


async def test_a_rate_per_gram_survives_the_rounding(
    real_async_db_session: AsyncSession, async_test_household
):
    db = real_async_db_session
    template = await _template_with_receipt(
        db, async_test_household.id, Decimal('1000'), Decimal('0.0234')
    )

    rate = await ValuationService.get_current_valuation_rate_async(
        db, async_test_household.id, template.id
    )

    assert rate == Decimal('0.0234')


async def test_a_rate_below_half_a_grosz_is_not_zero(
    real_async_db_session: AsyncSession, async_test_household
):
    db = real_async_db_session
    template = await _template_with_receipt(
        db, async_test_household.id, Decimal('1000'), Decimal('0.0021')
    )

    rate = await ValuationService.get_current_valuation_rate_async(
        db, async_test_household.id, template.id
    )

    assert rate == Decimal('0.0021')
    assert rate != Decimal('0')


async def test_the_batch_rate_agrees_with_the_single_one(
    real_async_db_session: AsyncSession, async_test_household
):
    """A BoM rollup reads rates in bulk; it must not read them coarser."""
    db = real_async_db_session
    template = await _template_with_receipt(
        db, async_test_household.id, Decimal('1000'), Decimal('0.0234')
    )

    rates = await ValuationService.get_valuation_rates_batch_async(
        db, async_test_household.id, [template.id]
    )

    assert rates[template.id] == Decimal('0.0234')


async def test_an_unpriced_receipt_inherits_the_full_rate(
    real_async_db_session: AsyncSession, async_test_household
):
    """The truncation used to be written into the next layer, not just returned."""
    db = real_async_db_session
    template = await _template_with_receipt(
        db, async_test_household.id, Decimal('1000'), Decimal('0.0234')
    )

    layer = await ValuationService._record_receipt_async(
        db, template, Decimal('500'), None, async_test_household.id
    )
    await db.flush()

    assert layer is not None
    assert layer.cost_basis == CostBasis.AVERAGE
    assert layer.unit_cost == Decimal('0.0234')


async def test_a_layer_says_the_same_before_and_after_it_is_stored(
    real_async_db_session: AsyncSession, async_test_household
):
    """A cost off an allocation is rounded by the code, not by the column.

    The freight spread over a delivery divides into as many digits as it
    likes: 100.00 over three units is 33.333333... each. The layer was built
    from that raw figure and left for Postgres to round on the way in, so the
    object handed back to the caller and the row that reached the table were
    two different numbers — and a caller that reads what it just posted, as
    the receipt executor does, read the one nothing else will ever see again.

    The rule the code applies is the one the outflow side already keeps: the
    total is taken from the exact cost, so the layers still add up to what was
    paid, and the per-unit figure is rounded to the four decimals its column
    holds.
    """
    db = real_async_db_session
    org_id = async_test_household.id
    template = ProductTemplate(
        organization_id=org_id, name='Freighted goods', sku=f'FG-{uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()

    layer = await ValuationService._record_receipt_async(
        db, template, Decimal('3'), Decimal('100') / Decimal('3'), org_id
    )
    assert layer is not None
    # Before it has been anywhere near the database.
    assert layer.unit_cost == Decimal('33.3333')
    assert layer.total_value == Decimal('100.00')

    await db.flush()
    layer_id = layer.id
    db.expunge_all()
    stored = await db.get(StockValuationLayer, layer_id)
    assert stored is not None
    assert stored.unit_cost == layer.unit_cost
    assert stored.total_value == layer.total_value


async def test_a_whole_price_is_untouched(
    real_async_db_session: AsyncSession, async_test_household
):
    """The control: a price that needs no rounding is not rounded."""
    db = real_async_db_session
    org_id = async_test_household.id
    template = ProductTemplate(
        organization_id=org_id, name='Plain goods', sku=f'PG-{uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()

    layer = await ValuationService._record_receipt_async(
        db, template, Decimal('4'), Decimal('2.50'), org_id
    )
    await db.flush()
    assert layer is not None
    assert layer.unit_cost == Decimal('2.50')
    assert layer.total_value == Decimal('10.00')
