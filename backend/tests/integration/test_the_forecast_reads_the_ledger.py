"""The spending forecast is made of what arrived, not of what the cards say.

The weekly series summed ``Item.purchase_price`` — the unit price, not the
price times the quantity, so one unit at 1000 weighed as much as a thousand
at 1 — dated by when the record was typed in. The receipt layers answer
both questions as asked: ``total_value`` is what the delivery cost, and its
business date is when it arrived. A price corrected on a card, with no
delivery behind it, is not spending and does not move the forecast.

The category drivers cannot come from the ledger (a layer knows no category)
and say so, row by row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.services.analytics.forecast import get_expense_forecast_async
from tests.integration._purchases import purchase_template, receipt_layer

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_WEEKS = 8


async def test_undated_layers_use_utc_weeks_in_any_session_timezone(
    real_async_db_session: AsyncSession, async_test_storage_location
) -> None:
    db = real_async_db_session
    org_id = async_test_storage_location.organization_id
    template = purchase_template(org_id, 'Midnight')
    db.add(template)
    await db.flush()
    sunday = date.today() - timedelta(days=(date.today().weekday() + 1) % 7 + 7)
    for hour, minute in [(23, 30), (24, 30)]:
        layer = receipt_layer(org_id, template.id, value='10', on=sunday)
        layer.document_date = None
        layer.created_at = datetime.combine(sunday, time(0), tzinfo=UTC) + timedelta(
            hours=hour, minutes=minute
        )
        db.add(layer)
    await db.flush()

    await db.execute(text("SET LOCAL TIME ZONE 'Europe/Warsaw'"))
    result = await get_expense_forecast_async(db, org_id)
    assert result.weeks_of_data == 2


async def _eight_weeks_of_two_at_ten(db: AsyncSession, org_id, location_id) -> None:
    """Every week: two units at 10.00 arrive, and the card says something else."""
    template = purchase_template(org_id, 'Widget')
    db.add(template)
    await db.flush()
    for week in range(_WEEKS):
        on = date.today() - timedelta(days=7 * week)
        db.add(receipt_layer(org_id, template.id, value='20.00', on=on, quantity='2'))
        db.add(
            Item(
                organization_id=org_id,
                storage_location_id=location_id,
                name=f'Widget {week}',
                quantity=Decimal('2'),
                # A card price the ledger never saw — and never will.
                purchase_price=Decimal('1000.00'),
                created_at=on,
            )
        )
    await db.flush()


async def test_the_weekly_rate_is_what_the_deliveries_cost(
    real_async_db_session: AsyncSession, async_test_storage_location
) -> None:
    db = real_async_db_session
    org_id = async_test_storage_location.organization_id
    await _eight_weeks_of_two_at_ten(db, org_id, async_test_storage_location.id)

    result = await get_expense_forecast_async(db, org_id, 'month')

    assert result.value_source == 'valuation_layers'
    assert result.weeks_of_data == _WEEKS
    # 20.00 a week: two at ten, not ten, and not the thousand on the card.
    assert result.historical_avg / 4.33 == pytest.approx(20.0, abs=0.01)


async def test_a_price_corrected_on_the_card_does_not_move_it(
    real_async_db_session: AsyncSession, async_test_storage_location
) -> None:
    db = real_async_db_session
    org_id = async_test_storage_location.organization_id
    await _eight_weeks_of_two_at_ten(db, org_id, async_test_storage_location.id)
    before = await get_expense_forecast_async(db, org_id, 'month')

    cards = await db.scalars(select(Item).where(Item.organization_id == org_id))
    for item in cards.all():
        item.purchase_price = Decimal('5.00')
    await db.flush()

    after = await get_expense_forecast_async(db, org_id, 'month')
    assert after.historical_avg == before.historical_avg
    assert after.predicted_spending == before.predicted_spending


async def test_the_category_drivers_say_they_are_off_the_cards(
    real_async_db_session: AsyncSession, async_test_storage_location
) -> None:
    db = real_async_db_session
    org_id = async_test_storage_location.organization_id
    await _eight_weeks_of_two_at_ten(db, org_id, async_test_storage_location.id)
    db.add(
        Item(
            organization_id=org_id,
            storage_location_id=async_test_storage_location.id,
            name='Unpriced widget',
            quantity=Decimal('1'),
        )
    )
    await db.flush()

    result = await get_expense_forecast_async(db, org_id, 'month')

    (driver,) = result.top_cost_drivers
    assert driver.value_source == 'purchase_price'
    assert driver.items_count == _WEEKS + 1
    assert driver.unpriced_count == 1
