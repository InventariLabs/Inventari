"""Expense forecast read-model.

Predicts future spending based on historical purchase trends, analyzes
waste-reduction potential, and identifies top cost-driver categories.
Domain-neutral: cost forecasting applies to any inventory vertical.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import CategoryCostDTO, ExpenseForecastDTO
from app.core.module_ownership import (
    general_rows,
    hidden_module_tags_async,
    outside_module_products,
)
from app.models.category import Category
from app.models.item import Item
from app.models.stock_valuation_layer import StockValuationLayer, layer_dated_at

from ._common import (
    get_org_currency_async,
    org_currency_filter,
    org_window_start_async,
    rounded,
)
from ._outflow_value import wasted_value_by_item_async

_MAX_ROWS = 500

# Below this many weeks a weekly spending rate is a number with no rate behind
# it. It is also the point at which the trend comparison (first three weeks
# against the last three) becomes possible, so a prediction is never just the
# historical average wearing a second label.
_MIN_WEEKS_FOR_FORECAST = 6


def _calculate_trend(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return rounded(((current - previous) / previous) * 100, 1)


async def _calculate_waste_potential_async(
    db: AsyncSession, organization_id: UUID, hidden_tags: set[str] | None = None
) -> float:
    """Annual savings achievable by halving monthly waste.

    The month's waste used to be summed out of
    ``ItemHistory.changes['wasted_cost']`` — a key nothing writes — so this
    number was always zero, and the forecast quietly promised no savings to
    an organization throwing away real money. It comes from the valuation
    ledger now, where the price of an outflow is recorded when it happens.
    """
    date_from = await org_window_start_async(db, organization_id, 30)

    wasted_value = await wasted_value_by_item_async(
        db, organization_id, date_from, hidden_tags
    )
    total_wasted = sum(wasted_value.values(), start=Decimal('0'))

    return rounded(total_wasted * Decimal('0.5') * 12)


async def _get_top_cost_drivers_async(
    db: AsyncSession, organization_id: UUID, hidden_tags: set[str] | None = None
) -> list[CategoryCostDTO]:
    """Top 5 categories by total purchase spend.

    Summed in the database. Read as rows the query took an arbitrary five
    hundred priced items and ranked whatever categories happened to be
    among them, so an organization with more than that could have its
    dearest category missing from a report about where the money went.
    """
    org_currency = await get_org_currency_async(db, organization_id)

    # Off the records, and saying so: a category is a property of the
    # record, and the cost ledger carries a product template and nothing
    # else, so there is no ledger figure per category to read (the same
    # wall the other per-category reports stand at). Times the quantity.
    # Without it one unit at 1000 and a thousand units at 1 came to the
    # same figure, and the ranking built on top of it was ordering by how
    # many rows carried a price.
    spent = func.sum(
        func.coalesce(Item.purchase_price, 0) * func.coalesce(Item.quantity, 0)
    )
    category_name = func.coalesce(Category.name, 'Other')

    rows = (
        await db.execute(
            select(
                category_name.label('category_name'),
                Category.code.label('category_code'),
                spent.label('total_spent'),
                func.count(Item.id).label('items_count'),
                func.count(Item.id)
                .filter(Item.purchase_price.is_(None))
                .label('unpriced_count'),
            )
            .select_from(Item)
            .outerjoin(Category, Item.category_id == Category.id)
            .where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                # Ours or unstated — the one policy every value report
                # shares; an exact match dropped every record that never
                # named a currency.
                org_currency_filter(Item.currency, org_currency),
                general_rows(hidden_tags),
            )
            # By the category, not its name — see the cost summary's
            # per-category rows for why a name is not a key.
            .group_by(Category.id, Category.name, Category.code)
            .order_by(spent.desc(), category_name, Category.id)
            .limit(5)
        )
    ).all()

    # total_wasted stays 0 here — the forecast view does not compute
    # per-category waste, only the aggregate potential above.
    return [
        CategoryCostDTO(
            category_name=row.category_name,
            category_code=row.category_code,
            total_spent=rounded(row.total_spent),
            total_wasted=0.0,
            items_count=row.items_count,
            unpriced_count=int(row.unpriced_count or 0),
        )
        for row in rows
    ]


def _weekly_series(weekly_spend: list[tuple[date, float]]) -> list[float]:
    """Spend per week, from the first week with a purchase to the last.

    Gaps are carried as zeros on purpose. A week nobody bought anything in is
    a week of zero spend, not a week that did not happen, and averaging only
    the weeks that happen to be non-empty reads a fortnightly shopper as a
    weekly one — and reads a single day of bulk intake as a permanent weekly
    rate.
    """
    buckets: dict[date, float] = {}
    for week_start, spent in weekly_spend:
        buckets[week_start] = buckets.get(week_start, 0.0) + spent

    if not buckets:
        return []

    first, last = min(buckets), max(buckets)
    span = (last - first).days // 7 + 1
    return [buckets.get(first + timedelta(weeks=i), 0.0) for i in range(span)]


def _forecast_confidence(series: list[float]) -> float:
    """How far the material under the prediction carries it.

    Two things decide that: how long the organization has been observed (a
    rate read off six weeks is a guess, off eighteen it is a rate) and how
    steady the spending was (a series that swings by its own size week after
    week predicts nothing at all).

    It used to be ``0.8 if annual_savings > 0`` — the potential for halving
    waste, a quantity the forecast is not made of. That is how a six-figure
    prediction came to stand next to a confidence bar reading 0%.
    """
    if not series:
        return 0.0

    coverage = min(len(series) / (_MIN_WEEKS_FOR_FORECAST * 3), 1.0)

    mean = statistics.mean(series)
    if mean <= 0:
        return 0.0
    # Coefficient of variation: spread measured against the size of what is
    # being spread, so a large steady spend does not look erratic.
    spread = statistics.pstdev(series) / mean
    steadiness = max(0.0, 1.0 - min(spread, 1.0))

    # Never 1.0 — a forecast that claims certainty is the one to distrust.
    return rounded(min(0.95, coverage * 0.5 + steadiness * 0.5))


async def get_expense_forecast_async(
    db: AsyncSession, organization_id: UUID, period: str = 'month'
) -> ExpenseForecastDTO:
    """Trend-driven prediction of future spend over a forecast period.

    A vertical module's products stay out unless the organization shows
    module data, as they stay out of the cost analysis beside it.
    """
    hidden = await hidden_module_tags_async(db, organization_id)
    date_from = await org_window_start_async(db, organization_id, 90)

    # What arrived each week, at what it cost, read from the receipt layers
    # on their business date. This used to sum the records' unit prices by
    # the day the record was typed in — one unit at 1000 weighed the same as
    # a thousand units at 1, and a delivery dated last month counted in the
    # week somebody entered it. Summed per week in the database: read as
    # rows the query kept the five hundred newest purchases in the window,
    # which empties the oldest weeks first -- and the trend comparison, first
    # three weeks against last three, then reads the truncation itself as a
    # household spending more.
    org_currency = await get_org_currency_async(db, organization_id)
    business_date = layer_dated_at()
    week_start = func.date_trunc('week', business_date)
    weekly = (
        await db.execute(
            select(week_start.label('week'), func.sum(StockValuationLayer.total_value))
            .where(
                StockValuationLayer.organization_id == organization_id,
                StockValuationLayer.direction == 'IN',
                outside_module_products(
                    StockValuationLayer.product_template_id, organization_id, hidden
                ),
                business_date >= date_from.date(),
                or_(
                    StockValuationLayer.currency == org_currency,
                    StockValuationLayer.currency.is_(None),
                ),
            )
            .group_by(week_start)
            .order_by(week_start)
        )
    ).all()

    series = _weekly_series([(row.week.date(), float(row[1] or 0)) for row in weekly])
    weeks_of_data = len(series)

    trend = 'no_data'
    trend_percentage: float | None = None
    predicted = 0.0
    historical_avg = 0.0
    confidence = 0.0

    if weeks_of_data >= _MIN_WEEKS_FOR_FORECAST:
        avg_weekly = statistics.mean(series)
        trend = 'stable'

        first_3 = statistics.mean(series[:3])
        last_3 = statistics.mean(series[-3:])
        if last_3 > first_3 * 1.1:
            trend = 'increasing'
        elif last_3 < first_3 * 0.9:
            trend = 'decreasing'
        trend_percentage = _calculate_trend(last_3, first_3)

        period_mult = {'week': 1, 'quarter': 13}.get(period, 4.33)
        predicted = avg_weekly * period_mult

        # Apply trend multiplier so the prediction reflects direction, not
        # just the historical mean.
        if trend_percentage is not None:
            predicted *= 1 + trend_percentage / 100

        historical_avg = avg_weekly * 4.33
        confidence = _forecast_confidence(series)

    annual_savings = await _calculate_waste_potential_async(db, organization_id, hidden)
    top_categories = await _get_top_cost_drivers_async(db, organization_id, hidden)

    return ExpenseForecastDTO(
        forecast_period=period,
        predicted_spending=rounded(predicted),
        historical_avg=rounded(historical_avg),
        trend=trend,
        trend_percentage=trend_percentage,
        top_cost_drivers=top_categories,
        waste_reduction_potential=annual_savings,
        confidence=confidence,
        weeks_of_data=weeks_of_data,
        weeks_required=_MIN_WEEKS_FOR_FORECAST,
    )
