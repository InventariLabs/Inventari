"""A tie at the cut of a cost or purchase ranking is settled by the name.

Every ranking here sorts the rows of a ``GROUP BY`` or a dict by one figure
and keeps the first five or ten, so products with an equal figure at the cut
came in the order the database or the insertion gave them, and two readings
of the same data could name a different product. Each ranking orders by the
figure, then by the name, and the tests below put the products in an
insertion order (and an id order) that is the reverse of the name order.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item, User
from app.models.category import Category
from app.models.storage_location import StorageLocation
from app.modules.stats._purchase_analysis import find_bulk_opportunities
from app.modules.stats._purchase_service import most_recurring
from app.services.analytics.cost import (
    _build_savings_opportunities,
    get_cost_summary_async,
)
from tests.integration._shelf import anchor_pending_records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Seven equal names, listed against their alphabetical order.
_TIED = ['Gamma', 'Foxtrot', 'Echo', 'Delta', 'Charlie', 'Bravo', 'Alpha']


def _ascending_ids(count: int) -> list[uuid.UUID]:
    first = uuid.uuid4().int & ~0xFF
    return [uuid.UUID(int=first + position) for position in range(count)]


async def test_the_category_cost_top_five_settles_a_tie_by_the_name(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    """Six categories of equal spend behind a leader: the first four by name."""
    db = real_async_db_session
    org_id = async_test_user.organization_id
    names = ['Leader', *_TIED]
    categories = [
        Category(id=category_id, organization_id=org_id, name=name)
        for category_id, name in zip(_ascending_ids(len(names)), names, strict=True)
    ]
    db.add_all(categories)
    await db.flush()
    db.add_all(
        Item(
            organization_id=org_id,
            storage_location_id=async_test_storage_location.id,
            category_id=category.id,
            name=f'{category.name} goods',
            quantity=Decimal('1'),
            purchase_price=Decimal('50')
            if category.name == 'Leader'
            else Decimal('10'),
        )
        for category in categories
    )
    await db.run_sync(anchor_pending_records)
    await db.flush()

    summary = await get_cost_summary_async(db, org_id)

    assert [c.category_name for c in summary.top_expensive_categories] == [
        'Leader',
        *sorted(_TIED)[:4],
    ]


async def test_the_recurring_products_top_ten_settles_a_tie_by_the_name() -> None:
    """Twelve products bought twice, behind one bought three times."""
    tied = [f'Product {letter}' for letter in 'LKJIHGFEDCBA']
    products = [{'name': name, 'total_purchases_last_6_months': 2} for name in tied]
    products.insert(5, {'name': 'Leader', 'total_purchases_last_6_months': 3})

    ranked = most_recurring(products)

    assert [p['name'] for p in ranked] == ['Leader', *sorted(tied)[:9]]


async def test_the_savings_opportunities_settle_a_tie_by_the_name() -> None:
    """Seven products that wasted the same, behind one that wasted more."""
    wasted = {
        name: {
            'category': 'Other',
            'category_code': None,
            'wasted_amount': Decimal('4'),
        }
        for name in _TIED
    }
    wasted = {
        'Leader': {**wasted['Alpha'], 'wasted_amount': Decimal('9')},
        **wasted,
    }

    opportunities = _build_savings_opportunities(wasted)

    assert [o.product_name for o in opportunities] == ['Leader', *sorted(_TIED)[:4]]


async def test_the_bulk_opportunities_settle_a_tie_by_the_name() -> None:
    """Seven products with the same potential saving, behind a dearer one."""

    def bought(price: str) -> dict[str, object]:
        return {
            'brand': '',
            'purchases': [object(), object(), object()],
            'total_quantity': Decimal('1'),
            'total_price': Decimal(price),
        }

    purchases = {name: bought('30') for name in _TIED}
    purchases = {'Leader': bought('60'), **purchases}

    opportunities = find_bulk_opportunities(purchases)

    assert [o['product'] for o in opportunities] == ['Leader', *sorted(_TIED)[:4]]
