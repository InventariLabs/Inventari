"""A cost nobody knows is not a cost of zero, whoever reads the layers.

Stock that arrives with nobody naming a price and no rate to borrow is posted
at 0.00 marked ``unknown``. The footer's rate left those layers out ("It is
not a cost"), but the rate a priceless receipt borrows averaged them in. So
the second priceless arrival of a product nobody priced — "Add 1 unit", a
surplus off a count, a file import — borrowed 0.00 from the first and wrote
it down as the organization's ``average``. From then on the ledger held a
known cost of zero for goods whose cost was never known, and the list stopped
counting the product as one without a cost history. After the opening
balance every shelf of stock that predates the ledger stands on ``unknown``
layers, so the first priceless receipt in every such organization did this.

One rule now decides whether a layer carries a cost, and every reader asks
it: the rate a priceless receipt borrows, the batch rate a bill of materials
is costed with, the footer's rate, the outflow that drains the layers and
the reports that ask whether an outflow was priced.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer
from app.services.items._query_get import _layer_average_rates
from app.services.valuation_service import ValuationService


async def _template(db: AsyncSession, org_id: UUID) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name='Nobody Priced This',
        sku=f'NP-{uuid4().hex[:8]}',
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


async def _stock_half_of_it_priced(
    db: AsyncSession, org_id: UUID, template: ProductTemplate
) -> None:
    """Six units nobody priced, then four bought at 10.00."""
    await ValuationService._record_receipt_async(
        db, template, Decimal('6'), None, org_id
    )
    await ValuationService._record_receipt_async(
        db, template, Decimal('4'), Decimal('10.00'), org_id
    )


async def _footer_rate(
    db: AsyncSession, organization, template_id: UUID
) -> Decimal | None:
    rates = _layer_average_rates(organization.currency)
    rate = await db.scalar(
        select(rates.c.rate).where(
            rates.c.organization_id == organization.id,
            rates.c.product_template_id == template_id,
        )
    )
    return None if rate is None else Decimal(str(rate)).quantize(Decimal('0.0001'))


@pytest.mark.integration
@pytest.mark.asyncio
class TestAPricelessReceiptBorrowsOnlyAKnownCost:
    async def test_over_stock_nobody_priced_it_stays_unknown(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)

        await ValuationService._record_receipt_async(
            db, template, Decimal('5'), None, org_id
        )
        await ValuationService._record_receipt_async(
            db, template, Decimal('1'), None, org_id
        )

        second = (await _layers(db, org_id, template.id, 'IN'))[1]
        assert second.cost_basis == CostBasis.UNKNOWN, (
            'nobody named a price and nobody ever paid one: there is no '
            'average to borrow, only a zero nobody stated'
        )

    async def test_beside_priced_stock_it_borrows_what_was_paid(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)
        await _stock_half_of_it_priced(db, org_id, template)

        await ValuationService._record_receipt_async(
            db, template, Decimal('2'), None, org_id
        )

        borrowed = (await _layers(db, org_id, template.id, 'IN'))[-1]
        assert borrowed.cost_basis == CostBasis.AVERAGE
        # 10.00, not 4.00: the six unpriced units are not six units at zero.
        assert borrowed.unit_cost == Decimal('10.0000')


@pytest.mark.integration
@pytest.mark.asyncio
class TestEveryReaderOfTheRateAgrees:
    async def test_on_stock_half_of_it_priced(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)
        await _stock_half_of_it_priced(db, org_id, template)

        single = await ValuationService.get_current_valuation_rate_async(
            db, org_id, template.id
        )
        batch = await ValuationService.get_valuation_rates_batch_async(
            db, org_id, [template.id]
        )
        footer = await _footer_rate(db, async_test_household, template.id)

        assert (single, batch[template.id], footer) == (
            Decimal('10.0000'),
            Decimal('10.0000'),
            Decimal('10.0000'),
        )

    async def test_on_stock_nobody_priced(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)
        await ValuationService._record_receipt_async(
            db, template, Decimal('5'), None, org_id
        )

        single = await ValuationService.get_current_valuation_rate_async(
            db, org_id, template.id
        )
        batch = await ValuationService.get_valuation_rates_batch_async(
            db, org_id, [template.id]
        )
        footer = await _footer_rate(db, async_test_household, template.id)

        assert (single, batch[template.id], footer) == (None, None, None)


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnOutflowOfStockNobodyPriced:
    async def test_is_not_an_outflow_that_cost_nothing(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)
        await ValuationService._record_receipt_async(
            db, template, Decimal('5'), None, org_id
        )

        posting = await ValuationService._post_delivery_async(
            db, template, Decimal('2'), org_id, reason='USED'
        )

        (out,) = await _layers(db, org_id, template.id, 'OUT')
        assert out.cost_basis == CostBasis.UNKNOWN
        # A production run pricing its output asks this, and "nobody knows"
        # must not come back as "free".
        assert posting.cost is None

    async def test_part_of_it_priced_is_exact_about_that_part_only(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org_id = async_test_household.id
        template = await _template(db, org_id)
        await _stock_half_of_it_priced(db, org_id, template)

        # Six unpriced units leave first, then two of the priced four.
        posting = await ValuationService._post_delivery_async(
            db, template, Decimal('8'), org_id, reason='USED'
        )

        (out,) = await _layers(db, org_id, template.id, 'OUT')
        assert out.cost_basis == CostBasis.UNKNOWN
        # What the priced layers gave up is on the books, to the grosz; it is
        # just not the whole cost of what left.
        assert out.total_value == Decimal('20.00')
        assert posting.cost is None


def _create_item(client, auth_headers, storage_id, **fields):
    payload = {'quantity': 1, 'location_id': str(storage_id), **fields}
    response = client.post('/api/v1/items', headers=auth_headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def _aggregates(client, auth_headers) -> dict:
    response = client.get('/api/v1/items/aggregates', headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


@pytest.mark.integration
class TestTheListFooter:
    def test_still_counts_a_product_without_a_cost_after_one_more_unit(
        self, client, auth_headers, test_storage_location
    ) -> None:
        _create_item(
            client,
            auth_headers,
            test_storage_location.id,
            name='Priced',
            quantity=2,
            purchase_price=3.00,
        )
        unpriced = _create_item(
            client, auth_headers, test_storage_location.id, name='Unpriced', quantity=5
        )
        assert _aggregates(client, auth_headers)['unpriced_count'] == 1

        # "Add 1 unit" on the list: the quantity raised by hand, no price.
        response = client.patch(
            f'/api/v1/items/{unpriced["id"]}/quantity',
            headers=auth_headers,
            json={'quantity': 6},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

        data = _aggregates(client, auth_headers)
        assert data['unpriced_count'] == 1, (
            'one more unit nobody priced does not give the product a cost history'
        )
        assert data['total_value'] == pytest.approx(6.0)
