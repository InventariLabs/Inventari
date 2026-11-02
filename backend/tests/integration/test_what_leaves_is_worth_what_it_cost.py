"""An outflow is worth the layers it actually consumed.

The drain was FIFO and the valuation was the average of what remained: two
formulas on one move. Ten units bought at 1.00 and ten at 3.00, then ten
delivered — FIFO took the 10.00 layer off the shelf and the outgoing row was
written at 20.00. The books then held 40.00 bought, 20.00 gone and 30.00
standing, so 10.00 came from nowhere, and the consumption report and the stock
value could never be reconciled against the purchases.

IAS 2 asks for one formula applied consistently. The balance sheet side was
already FIFO — stock value, aging and the drain itself all read the layers in
business-date order — so the outgoing row is the one number that had to move.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer
from app.services.valuation_service import ValuationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _template(db: AsyncSession, org_id) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name='Two-price widget',
        sku=f'TPW-{uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def _two_receipts(db: AsyncSession, org_id, template: ProductTemplate) -> None:
    """Ten at 1.00, then ten at 3.00 — the worked example."""
    await ValuationService._record_receipt_async(
        db, template, Decimal('10'), Decimal('1.00'), org_id
    )
    await ValuationService._record_receipt_async(
        db, template, Decimal('10'), Decimal('3.00'), org_id
    )
    await db.flush()


async def _layers(
    db: AsyncSession, template: ProductTemplate, direction: str
) -> list[StockValuationLayer]:
    rows = await db.scalars(
        select(StockValuationLayer)
        .where(
            StockValuationLayer.product_template_id == template.id,
            StockValuationLayer.direction == direction,
        )
        .order_by(StockValuationLayer.created_at, StockValuationLayer.id)
    )
    return list(rows.all())


async def test_an_outflow_is_worth_the_layers_it_consumed(
    real_async_db_session: AsyncSession, async_test_household
):
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)
    await _two_receipts(db, org_id, template)

    await ValuationService._post_delivery_async(db, template, Decimal('10'), org_id)
    await db.flush()

    (out,) = await _layers(db, template, 'OUT')
    assert out.total_value == Decimal('10.00')
    assert out.unit_cost == Decimal('1.0000')
    assert out.cost_basis == CostBasis.FIFO


async def test_the_stock_equation_closes(
    real_async_db_session: AsyncSession, async_test_household
):
    """Opening plus purchases minus what left equals what stands."""
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)
    await _two_receipts(db, org_id, template)

    await ValuationService._post_delivery_async(db, template, Decimal('10'), org_id)
    await db.flush()

    bought = sum(layer.total_value for layer in await _layers(db, template, 'IN'))
    gone = sum(layer.total_value for layer in await _layers(db, template, 'OUT'))
    standing = sum(
        layer.remaining_qty * layer.unit_cost
        for layer in await _layers(db, template, 'IN')
    )

    assert bought - gone == standing


async def test_an_outflow_spanning_two_layers_blends_their_costs(
    real_async_db_session: AsyncSession, async_test_household
):
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)
    await _two_receipts(db, org_id, template)

    await ValuationService._post_delivery_async(db, template, Decimal('15'), org_id)
    await db.flush()

    (out,) = await _layers(db, template, 'OUT')
    # Ten at 1.00 and five at 3.00.
    assert out.total_value == Decimal('25.00')
    assert out.unit_cost == Decimal('1.6667')
    assert out.cost_basis == CostBasis.FIFO


async def test_an_outflow_the_layers_cannot_cover_says_it_does_not_know(
    real_async_db_session: AsyncSession, async_test_household
):
    """The part that left with no cost history behind it is not a zero."""
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)
    await _two_receipts(db, org_id, template)

    await ValuationService._post_delivery_async(db, template, Decimal('30'), org_id)
    await db.flush()

    (out,) = await _layers(db, template, 'OUT')
    # Everything the layers held — and no invented cost for the missing ten.
    assert out.total_value == Decimal('40.00')
    assert out.cost_basis == CostBasis.UNKNOWN


async def test_an_outflow_across_two_currencies_has_no_sum(
    real_async_db_session: AsyncSession, async_test_household
):
    """Amounts in different money do not add, so none is written.

    Layers drain by age, not by what they were bought in, so a template with
    a foreign receipt in its history can hand the drain two currencies. The
    rate this used to be posted at refused a mixed batch; summing the costs
    instead must refuse it for the same reason.
    """
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)

    await ValuationService._record_receipt_async(
        db, template, Decimal('10'), Decimal('1.00'), org_id
    )
    await ValuationService._record_receipt_async(
        db, template, Decimal('10'), Decimal('3.00'), org_id, None, 'XYZ'
    )
    await db.flush()

    await ValuationService._post_delivery_async(db, template, Decimal('15'), org_id)
    await db.flush()

    (out,) = await _layers(db, template, 'OUT')
    assert out.total_value == Decimal('0.00')
    assert out.cost_basis == CostBasis.UNKNOWN
