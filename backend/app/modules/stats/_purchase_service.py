"""
Purchase pattern analysis service.

Analyzes recurring purchases, seasonal trends, price volatility,
and identifies bulk purchase opportunities.
"""

# architecture: allow_direct_db_access
# reason: Complex aggregation and window queries for purchase pattern analysis cannot be expressed through CoreAPI

import statistics
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_sdk import general_rows, hidden_module_tags_async
from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory
from app.models.organization import Organization
from app.services.analytics._common import (
    get_internal_storage_ids_async,
    org_window_start_async,
)

from ._purchase_analysis import (
    analyze_seasonality,
    find_bulk_opportunities,
    parse_product_purchases,
    rounded,
)
from .constants import MAX_ANALYTICS_ROWS


def _born_as_a_purchase(organization_id: UUID) -> ColumnElement[bool]:
    """True for a record whose birth was a purchase, not a move of goods.

    A purchase is positively recognisable: it is entered by hand, imported,
    scanned, added by an AI agent, or received on a warehouse receipt (a
    document of type ``IN``). Entered by hand, imported and scanned births say
    nothing about why in their history; the agent's add and the receipt say so
    and are let through by name, and so is the note that a unit other than the
    card's was chosen, which says how the quantity was typed, not why the
    record exists. Every other way a record comes to exist (a
    production run's output, the remainder of a split transfer, a stock
    count's surplus, an opened package, a reversed run's ingredient) carries
    some other reason, so it leaves the record out and a new kind of birth
    stays out without being listed here.
    """
    reason = ItemHistory.changes['reason'].as_string()
    return (
        ~select(ItemHistory.id)
        .where(
            ItemHistory.organization_id == organization_id,
            ItemHistory.item_id == Item.id,
            ItemHistory.action == ItemAction.CREATED.value,
            reason.isnot(None),
            reason.notin_(('mcp_create', 'unit_chosen_over_template')),
            ~and_(
                reason == 'document_execution',
                ItemHistory.changes['document_type'].as_string() == 'IN',
            ),
        )
        .exists()
    )


async def _batch_assess_volatility(
    db: AsyncSession,
    organization_id: UUID,
    product_names: list[str],
    purchase_filters: list[ColumnElement[bool]],
) -> dict[str, str]:
    """Batch-load prices for all products and compute volatility in one query.

    *purchase_filters* are the conditions the purchase count reads its records
    by, so the price spread is measured over the purchases that were counted.
    """
    if not product_names:
        return {}

    rows = (
        await db.execute(
            select(Item.name, Item.purchase_price)
            .where(
                Item.organization_id == organization_id,
                Item.name.in_(product_names),
                Item.purchase_price.isnot(None),
                *purchase_filters,
            )
            .limit(MAX_ANALYTICS_ROWS * 2)
        )
    ).all()

    prices_by_name: dict[str, list[float]] = {}
    for name, price in rows:
        if price is not None:
            prices_by_name.setdefault(name, []).append(float(price))

    result: dict[str, str] = {}
    for name in product_names:
        prices = prices_by_name.get(name, [])
        if len(prices) < 2:
            result[name] = 'insufficient_data'
            continue
        avg = statistics.mean(prices)
        std = statistics.stdev(prices)
        cv = (std / avg) * 100
        if cv > 15:
            result[name] = 'high'
        elif cv > 8:
            result[name] = 'medium'
        else:
            result[name] = 'low'
    return result


def most_recurring(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ten products bought most often; equal ones in the order of their names.

    The rows come out of a ``GROUP BY`` in no order of their own, so a
    ranking by the count alone left a tie at the tenth place to the order the
    database returned them in.
    """
    return sorted(
        products,
        key=lambda x: (
            -x['total_purchases_last_6_months'],
            x['name'].casefold(),
            x['name'],
        ),
    )[:10]


async def get_purchase_patterns_async(
    db: AsyncSession, organization_id: UUID
) -> dict[str, Any]:
    date_from = await org_window_start_async(db, organization_id, 180)

    # The same rows the cost analysis counts. Summed over every row of the
    # tenant instead, this read reported one product as having cost more than
    # the organization spent in total — a whole smaller than one of its parts.
    # A vertical module's records and places stay out with it, unless the
    # organization shows module data.
    hidden = await hidden_module_tags_async(db, organization_id)
    storage_ids = await get_internal_storage_ids_async(db, organization_id, hidden)
    org_currency = await db.scalar(
        select(Organization.currency).where(Organization.id == organization_id)
    )

    purchase_filters: list[ColumnElement[bool]] = [
        Item.organization_id == organization_id,
        Item.storage_location_id.in_(storage_ids),
        Item.is_deleted.is_(False),
        Item.created_at >= date_from,
        _born_as_a_purchase(organization_id),
        general_rows(hidden),
        or_(
            Item.currency == org_currency,
            Item.currency.is_(None),
        ),
    ]

    product_rows = (
        await db.execute(
            select(
                Item.name,
                func.coalesce(Item.brand, '').label('brand'),
                func.coalesce(Category.name, 'Other').label('category'),
                Category.code.label('category_code'),
                func.count(Item.id).label('purchase_count'),
                func.sum(func.coalesce(Item.quantity, 0)).label('total_quantity'),
                # The price is per unit, so what was spent is price × quantity.
                func.sum(
                    func.coalesce(Item.purchase_price, 0)
                    * func.coalesce(Item.quantity, 0)
                ).label('total_price'),
                func.array_agg(Item.created_at).label('purchase_dates'),
            )
            .outerjoin(Category, Item.category_id == Category.id)
            .where(*purchase_filters)
            .group_by(
                Item.name,
                Item.brand,
                func.coalesce(Item.brand, ''),
                Category.name,
                func.coalesce(Category.name, 'Other'),
                Category.code,
            )
            .limit(MAX_ANALYTICS_ROWS)
        )
    ).all()

    product_purchases = parse_product_purchases(product_rows)

    top_recurring = []
    candidate_names = [
        name for name, data in product_purchases.items() if len(data['purchases']) >= 2
    ]
    volatility_map = await _batch_assess_volatility(
        db, organization_id, candidate_names, purchase_filters
    )

    for product_name in candidate_names:
        data = product_purchases[product_name]
        purchase_dates = sorted(data['purchases'])
        intervals = [
            (purchase_dates[i] - purchase_dates[i - 1]).days
            for i in range(1, len(purchase_dates))
        ]
        avg_frequency = rounded(statistics.mean(intervals), 1) if intervals else 0.0

        avg_price = data['total_price'] / len(data['purchases'])
        avg_quantity = data['total_quantity'] / len(data['purchases'])

        top_recurring.append(
            {
                'name': product_name,
                'brand': data['brand'],
                'category': data['category'],
                'category_code': data['category_code'],
                'purchase_frequency_days': avg_frequency,
                'total_purchases_last_6_months': len(data['purchases']),
                'avg_price': rounded(avg_price),
                'avg_quantity': rounded(avg_quantity),
                'total_spent': rounded(data['total_price']),
                'price_volatility': volatility_map.get(
                    product_name, 'insufficient_data'
                ),
            }
        )

    top_recurring = most_recurring(top_recurring)

    seasonal_products = analyze_seasonality(product_purchases)
    bulk_opportunities = find_bulk_opportunities(product_purchases)

    return {
        'top_recurring_products': top_recurring,
        'seasonal_products': seasonal_products,
        'bulk_opportunities': bulk_opportunities,
        'value_source': 'purchase_price',
    }
