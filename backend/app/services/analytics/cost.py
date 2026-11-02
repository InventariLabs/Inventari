"""Cost summary read-model.

Total spent, total wasted, waste percentage, per-category cost breakdown,
monthly trend, and savings opportunities. Domain-neutral: cost analysis
applies to any inventory vertical.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    CategoryCostDTO,
    CostSummaryDTO,
    MonthlyTrendDTO,
    SavingsOpportunityDTO,
)
from app.core.db_utils import in_ids
from app.core.module_ownership import (
    general_rows,
    hidden_module_tags_async,
    outside_module_products,
)
from app.models import Category, Item, ItemHistory
from app.models.item_history import DISPOSAL_ACTIONS
from app.models.stock_valuation_layer import StockValuationLayer
from app.services.analytics._outflow_value import (
    wasted_value_by_item_async,
    window_is_valued_async,
)
from app.services.storage._queries import list_storage_ids_async

from ._common import (
    get_org_currency_async,
    org_today_async,
    org_window_start_async,
    rounded,
)


def _empty_summary() -> CostSummaryDTO:
    """Return a zeroed-out summary for orgs with no storage locations."""
    return CostSummaryDTO(
        total_spent=0.0,
        total_wasted=0.0,
        waste_value_percentage=0.0,
        top_expensive_categories=[],
        monthly_trend=[],
        savings_opportunities=[],
    )


async def _resolve_period_window_async(
    db: AsyncSession, organization_id: UUID, period: str
) -> datetime:
    """When the window opens, as an instant in the organization's own day.

    A bare date compared against a timestamp column is read as midnight UTC,
    so "the last thirty days" began at a moment with nothing to do with the
    organization's morning.
    """
    period_map = {'day': 1, 'week': 7, 'year': 365}
    return await org_window_start_async(db, organization_id, period_map.get(period, 30))


async def _compute_total_spent_async(
    db: AsyncSession,
    organization_id: UUID,
    org_currency: str,
    date_from: datetime,
    hidden_tags: set[str] | None = None,
) -> Decimal:
    """What the period's receipts cost, read from the valuation ledger.

    The denominator of the waste percentage used to be the purchase value
    of what the window's receipts had *left* — an item bought and then
    thrown away left the denominator while its disposal stayed in the
    numerator, and the percentage crossed 100. Both figures now read the
    same population: what arrived in the window, priced by the layers,
    in the organization's money.

    That last clause is a filter, not a figure of speech. The rewrite onto
    the ledger dropped the ``storage_ids`` this used to be narrowed by and
    put nothing in its place, so every tenant was handed the sum of all of
    them -- see the organization filter first in the WHERE clause below.

    *hidden_tags* leaves a vertical module's products out
    (:func:`hidden_module_tags_async`): a household's family laptop is not
    what its pantry cost.
    """
    arrived_from = date_from.date()
    total_spent_row = await db.scalar(
        select(func.coalesce(func.sum(StockValuationLayer.total_value), 0)).where(
            StockValuationLayer.organization_id == organization_id,
            StockValuationLayer.direction == 'IN',
            outside_module_products(
                StockValuationLayer.product_template_id, organization_id, hidden_tags
            ),
            func.coalesce(
                StockValuationLayer.document_date,
                cast(StockValuationLayer.created_at, Date),
            )
            >= arrived_from,
            or_(
                StockValuationLayer.currency == org_currency,
                StockValuationLayer.currency.is_(None),
            ),
        )
    )
    return Decimal(str(total_spent_row or 0))


async def _count_other_currency_items_async(
    db: AsyncSession,
    organization_id: UUID,
    org_currency: str,
    date_from: datetime,
    hidden_tags: set[str] | None = None,
) -> int:
    """Receipts in the window whose currency is not the organization's.

    They are correctly left out of the sum — two currencies do not add — but
    leaving them out silently turned "we cannot add these up" into "0.00".
    """
    arrived_from = date_from.date()
    count = await db.scalar(
        select(func.count(StockValuationLayer.id)).where(
            StockValuationLayer.organization_id == organization_id,
            StockValuationLayer.direction == 'IN',
            outside_module_products(
                StockValuationLayer.product_template_id, organization_id, hidden_tags
            ),
            func.coalesce(
                StockValuationLayer.document_date,
                cast(StockValuationLayer.created_at, Date),
            )
            >= arrived_from,
            StockValuationLayer.currency.isnot(None),
            StockValuationLayer.currency != org_currency,
        )
    )
    return int(count or 0)


async def _compute_wasted_by_product_async(
    db: AsyncSession,
    organization_id: UUID,
    storage_ids: list[UUID],
    date_from: datetime,
    hidden_tags: set[str] | None = None,
) -> tuple[Decimal, dict[str, dict]]:
    """What was thrown away, per product, priced by the valuation ledger.

    The figure used to come from ``ItemHistory.changes['wasted_cost']``, a key
    nothing in the application writes — so this whole report read zero in
    every organization, and the "Wasted" tile on the cost screen was a
    confident 0.00 over however much had gone in the bin.

    An outflow is priced once, when it happens, and the ledger keeps it. See
    ``_outflow_value`` for what that leaves unknowable: outflows from before
    the ledger's outgoing half existed, and records with no product template.

    Returns (total_wasted, wasted_by_product) where wasted_by_product maps
    product name → {name, category_id, category, category_code, wasted_amount}.
    """
    # Trusts the filter: a row here says only which records had a disposal,
    # and what each one is worth comes from the ledger's disposal layers — a
    # row of another kind could add a product name, never a value. One line
    # per record, not per event: nothing about the event itself is read.
    discarded_result = await db.execute(
        select(
            ItemHistory.item_id,
            Item.name,
            Item.category_id,
            Category.name.label('category_name'),
            Category.code.label('category_code'),
        )
        .distinct()
        .join(Item, ItemHistory.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .where(
            ItemHistory.organization_id == organization_id,
            ItemHistory.action.in_(DISPOSAL_ACTIONS),
            ItemHistory.created_at >= date_from,
            in_ids(Item.storage_location_id, storage_ids),
            general_rows(hidden_tags),
        )
    )
    discarded_history = discarded_result.all()
    wasted_value = await wasted_value_by_item_async(db, organization_id, date_from)

    total_wasted = Decimal('0')
    wasted_by_product: dict[str, dict] = {}
    counted: set = set()
    for record in discarded_history:
        name = record.name
        wasted_by_product.setdefault(
            name,
            {
                'name': name,
                'category_id': record.category_id,
                'category': record.category_name or 'Other',
                'category_code': record.category_code,
                'wasted_amount': Decimal('0'),
            },
        )
        # Once per record: the ledger already summed that record's outflows
        # over the window, so adding it per history row would multiply it by
        # the number of times the shelf was visited.
        if record.item_id is not None and record.item_id not in counted:
            counted.add(record.item_id)
            value = wasted_value.get(record.item_id, Decimal('0'))
            wasted_by_product[name]['wasted_amount'] += value
            total_wasted += value
    return total_wasted, wasted_by_product


async def _compute_category_costs_async(
    db: AsyncSession,
    storage_ids: list[UUID],
    org_currency: str,
    date_from: datetime,
    wasted_by_product: dict[str, dict],
    hidden_tags: set[str] | None = None,
) -> dict[UUID | None, dict]:
    """Per-category spent + items_count, merged with wasted amounts.

    The top-5 by total_spent is applied by the caller.

    Spent is price times quantity off the records: a category is a property
    of the record, and the cost ledger knows only the product template, so
    there is no ledger figure per category to read. The rows say so
    (``value_source``) and count the records that carried no price, which
    used to be filtered out of the count as well as the sum — a category of
    ten unpriced records reported as no records at all.

    Keyed by the category's id, not its name: two categories may share a
    name, and the code that names a seeded category in the reader's
    language belongs to one of them, not to the spelling.
    """
    category_costs_result = await db.execute(
        select(
            Category.id.label('category_id'),
            func.coalesce(Category.name, 'Other').label('category_name'),
            Category.code.label('category_code'),
            func.coalesce(
                func.sum(
                    func.coalesce(Item.purchase_price, 0)
                    * func.coalesce(Item.quantity, 0)
                ),
                0,
            ).label('total_spent'),
            func.count(Item.id).label('items_count'),
            func.count(Item.id)
            .filter(Item.purchase_price.is_(None))
            .label('unpriced_count'),
        )
        .outerjoin(Category, Item.category_id == Category.id)
        .where(
            in_ids(Item.storage_location_id, storage_ids),
            Item.is_deleted.is_(False),
            or_(
                Item.currency == org_currency,
                Item.currency.is_(None),
            ),
            Item.created_at >= date_from,
            general_rows(hidden_tags),
        )
        .group_by(Category.id, Category.name, Category.code)
    )
    category_costs: dict[UUID | None, dict] = {}
    for row in category_costs_result.all():
        category_costs[row.category_id] = {
            'category_name': row.category_name,
            'category_code': row.category_code,
            'total_spent': Decimal(str(row.total_spent or 0)),
            'total_wasted': Decimal('0'),
            'items_count': row.items_count,
            'unpriced_count': int(row.unpriced_count or 0),
        }

    for product_data in wasted_by_product.values():
        category_id = product_data['category_id']
        if category_id in category_costs:
            category_costs[category_id]['total_wasted'] += product_data['wasted_amount']
    return category_costs


def _build_savings_opportunities(
    wasted_by_product: dict[str, dict],
) -> list[SavingsOpportunityDTO]:
    """Top-5 products with waste, each paired with a planning suggestion."""
    return [
        SavingsOpportunityDTO(
            product_name=name,
            category_name=data['category'],
            category_code=data['category_code'],
            wasted_amount=rounded(data['wasted_amount']),
            suggestion=f'Consider smaller packaging or better shopping planning for {name}',
        )
        for name, data in sorted(
            wasted_by_product.items(), key=lambda x: x[1]['wasted_amount'], reverse=True
        )[:5]
        if data['wasted_amount'] > 0
    ]


async def _compute_monthly_trend_async(
    db: AsyncSession,
    organization_id: UUID,
    org_currency: str,
    date_from: datetime,
    today: date,
    hidden_tags: set[str] | None = None,
) -> list[MonthlyTrendDTO]:
    """Last 6 months spent + wasted, aligned to month-start buckets.

    Both figures come from the cost ledger, on the business date of the
    layer. Spent used to be price times quantity off the records, dated by
    when the record was typed in; wasted read ``changes['wasted_cost']`` off
    the history, a key nothing writes, so it was zero in every month for
    every organization. A receipt is an IN layer worth what it cost, a
    disposal is an OUT layer with the reason on it, and the ledger already
    prices both once, when they happen.
    """
    business_date = func.coalesce(
        StockValuationLayer.document_date,
        cast(StockValuationLayer.created_at, Date),
    )
    month_label = func.to_char(func.date_trunc('month', business_date), 'YYYY-MM')
    in_window = (
        StockValuationLayer.organization_id == organization_id,
        outside_module_products(
            StockValuationLayer.product_template_id, organization_id, hidden_tags
        ),
        business_date >= date_from.date(),
        or_(
            StockValuationLayer.currency == org_currency,
            StockValuationLayer.currency.is_(None),
        ),
    )

    monthly_spent_result = await db.execute(
        select(
            month_label.label('month'),
            func.coalesce(func.sum(StockValuationLayer.total_value), 0).label('spent'),
        )
        .where(*in_window, StockValuationLayer.direction == 'IN')
        .group_by(month_label)
    )
    monthly_spent_map = {
        row.month: Decimal(str(row.spent or 0)) for row in monthly_spent_result.all()
    }

    monthly_wasted_result = await db.execute(
        select(
            month_label.label('month'),
            func.coalesce(func.sum(StockValuationLayer.total_value), 0).label('wasted'),
        )
        .where(
            *in_window,
            StockValuationLayer.direction == 'OUT',
            StockValuationLayer.reason.in_(DISPOSAL_ACTIONS),
        )
        .group_by(month_label)
    )
    monthly_wasted_map: dict[str, Decimal] = {
        row.month: Decimal(str(row.wasted or 0)) for row in monthly_wasted_result.all()
    }

    # Step back whole calendar months: a 30-day chunk drifts across short
    # months — from March 1, "30 days ago" lands on January 30, so February
    # never appears and January is labelled twice.
    month_labels: list[str] = []
    year, month = today.year, today.month
    for _ in range(6):
        month_labels.append(f'{year:04d}-{month:02d}')
        month -= 1
        if month == 0:
            month, year = 12, year - 1

    monthly_trend = [
        MonthlyTrendDTO(
            month=month_name,
            spent=rounded(monthly_spent_map.get(month_name, 0)),
            wasted=rounded(monthly_wasted_map.get(month_name, 0)),
        )
        for month_name in reversed(month_labels)
    ]
    return monthly_trend


async def get_cost_summary_async(
    db: AsyncSession, organization_id: UUID, period: str = 'month'
) -> CostSummaryDTO:
    """Cost analysis for the given period window.

    A vertical module's records and products stay out unless the organization
    shows module data, as they stay out of the products list and the overview
    beside this report — the family laptop topped a household's "most
    expensive categories".
    """
    storage_ids = await list_storage_ids_async(db, organization_id)
    if not storage_ids:
        return _empty_summary()
    hidden = await hidden_module_tags_async(db, organization_id)

    today = await org_today_async(db, organization_id)
    date_from = await _resolve_period_window_async(db, organization_id, period)
    org_currency = await get_org_currency_async(db, organization_id)

    total_spent = await _compute_total_spent_async(
        db, organization_id, org_currency, date_from, hidden
    )

    total_wasted, wasted_by_product = await _compute_wasted_by_product_async(
        db, organization_id, storage_ids, date_from, hidden
    )
    # See ``CostSummaryDTO.total_wasted``: an unpriced window is unknown,
    # and a percentage of an unknown is unknown too.
    valued = await window_is_valued_async(db, organization_id, date_from)
    waste_value_percentage = (
        (total_wasted / total_spent * 100) if total_spent > 0 else Decimal('0')
    )

    category_costs = await _compute_category_costs_async(
        db, storage_ids, org_currency, date_from, wasted_by_product, hidden
    )
    top_expensive_categories = [
        CategoryCostDTO(
            **{
                **data,
                'total_spent': rounded(data['total_spent']),
                'total_wasted': rounded(data['total_wasted']),
            }
        )
        for data in sorted(
            category_costs.values(), key=lambda x: x['total_spent'], reverse=True
        )[:5]
    ]

    savings_opportunities = _build_savings_opportunities(wasted_by_product)

    monthly_trend = await _compute_monthly_trend_async(
        db, organization_id, org_currency, date_from, today, hidden
    )

    excluded = await _count_other_currency_items_async(
        db, organization_id, org_currency, date_from, hidden
    )

    return CostSummaryDTO(
        total_spent=rounded(total_spent),
        total_wasted=rounded(total_wasted) if valued else None,
        waste_value_percentage=rounded(waste_value_percentage) if valued else None,
        top_expensive_categories=top_expensive_categories,
        monthly_trend=monthly_trend,
        savings_opportunities=savings_opportunities,
        excluded_other_currency_count=excluded,
    )
