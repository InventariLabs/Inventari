"""The statistics leave a module's records out the way the products list does.

A household switched equipment on and registered its family laptop. The
products list left the laptop out — the organization's setting keeps module
data out of general lists — while the statistics beside it counted it among
the records, its storage among the places, "Laptop" among the categories and
its age in the stock age. The setting is the organization's, so the reports
read it themselves; with the setting on, the laptop is counted everywhere.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_scope import get_claimed_context_tags
from app.models import Item, User
from app.models.category import Category
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.services.analytics.dashboard import (
    get_stats_by_category_async,
    get_stats_by_storage_async,
)
from app.services.analytics.overview import get_overview_async
from app.services.analytics.rotation import get_rotation_analysis_async
from tests.integration._shelf import anchor_pending_records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _pantry_and_a_laptop(
    db: AsyncSession, user: User, pantry: StorageLocation
) -> StorageLocation:
    tag = sorted(get_claimed_context_tags())[0]
    it_storage = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        name=f'IT Storage {uuid.uuid4().hex[:6]}',
        usage='internal',
        context_tag=tag,
    )
    laptops = Category(
        organization_id=user.organization_id, name='Laptop', context_tag=tag
    )
    db.add_all([it_storage, laptops])
    await db.flush()
    week_ago = date.today() - timedelta(days=7)
    db.add_all(
        [
            Item(
                organization_id=user.organization_id,
                storage_location_id=pantry.id,
                name='Rice',
                quantity=Decimal('1'),
                added_date=week_ago,
            ),
            Item(
                organization_id=user.organization_id,
                storage_location_id=it_storage.id,
                category_id=laptops.id,
                name='Family laptop',
                quantity=Decimal('1'),
                added_date=week_ago,
            ),
        ]
    )
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return it_storage


async def _show_module_data(db: AsyncSession, user: User, value: bool) -> None:
    org = await db.get(Organization, user.organization_id)
    assert org is not None
    org.settings = {**(org.settings or {}), 'show_module_data': value}
    await db.flush()


async def test_the_statistics_leave_the_laptop_out(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    db = real_async_db_session
    it_storage = await _pantry_and_a_laptop(
        db, async_test_user, async_test_storage_location
    )
    org_id = async_test_user.organization_id

    overview = await get_overview_async(db, org_id)
    by_category = await get_stats_by_category_async(db, org_id)
    by_storage = await get_stats_by_storage_async(db, org_id)
    rotation = await get_rotation_analysis_async(db, org_id)

    assert overview.total_items == 1
    assert it_storage.id not in {s.location_id for s in by_storage}
    assert 'Laptop' not in {c.category_name for c in by_category}
    assert sum(c.items_count for c in by_category) == 1
    assert rotation.active_items_count == 1
    assert 'Laptop' not in {r.category_name for r in rotation.rotation_by_category}

    # The places count is the same places the breakdown lists.
    await _show_module_data(db, async_test_user, True)
    everything = await get_overview_async(db, org_id)
    assert everything.total_locations == overview.total_locations + 1


async def test_with_module_data_shown_the_laptop_is_counted(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    db = real_async_db_session
    it_storage = await _pantry_and_a_laptop(
        db, async_test_user, async_test_storage_location
    )
    await _show_module_data(db, async_test_user, True)
    org_id = async_test_user.organization_id

    overview = await get_overview_async(db, org_id)
    by_category = await get_stats_by_category_async(db, org_id)
    by_storage = await get_stats_by_storage_async(db, org_id)
    rotation = await get_rotation_analysis_async(db, org_id)

    assert overview.total_items == 2
    assert it_storage.id in {s.location_id for s in by_storage}
    assert 'Laptop' in {c.category_name for c in by_category}
    assert rotation.active_items_count == 2


async def _bought_twice(
    db: AsyncSession,
    user: User,
    location: StorageLocation,
    name: str,
    price: Decimal,
    category: Category | None = None,
) -> None:
    """Two records of one product, priced, received into the cost ledger.

    Last touched three months ago, so the alerts call it forgotten, and
    bought twice, so the purchase patterns call it recurring; a little of the
    second record has been used since.
    """
    from datetime import UTC, datetime

    from app.models.product_template import ProductTemplate
    from app.services.valuation_service import ValuationService

    template = ProductTemplate(organization_id=user.organization_id, name=name)
    db.add(template)
    await db.flush()
    long_ago = datetime.now(UTC) - timedelta(days=90)
    for _ in range(2):
        await ValuationService._record_receipt_async(
            db, template, Decimal('1'), price, user.organization_id
        )
    records = []
    for _ in range(2):
        records.append(
            Item(
                organization_id=user.organization_id,
                storage_location_id=location.id,
                template_id=template.id,
                category_id=category.id if category else None,
                name=name,
                quantity=Decimal('1'),
                purchase_price=price,
                added_date=long_ago.date(),
                updated_at=long_ago,
            )
        )
    db.add_all(records)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    from app.models.item_history import ItemAction, ItemHistory

    db.add(
        ItemHistory(
            organization_id=user.organization_id,
            item_id=records[1].id,
            user_id=user.id,
            action=ItemAction.USED.value,
            changes={'qty': 0.5},
        )
    )
    await db.flush()


async def _a_pantry_and_two_laptops(
    db: AsyncSession, user: User, pantry: StorageLocation
) -> None:
    tag = sorted(get_claimed_context_tags())[0]
    laptops = Category(
        organization_id=user.organization_id, name='Laptop', context_tag=tag
    )
    db.add(laptops)
    await db.flush()
    await _bought_twice(db, user, pantry, 'Rice', Decimal('5'))
    # On the pantry shelf, filed under the module's category: the category
    # alone makes it the module's record.
    await _bought_twice(db, user, pantry, 'Family laptop', Decimal('3000'), laptops)


async def test_the_money_reports_and_alerts_leave_the_laptop_out(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    from app.modules.stats._alerts_service import get_smart_alerts_async
    from app.modules.stats._purchase_service import get_purchase_patterns_async
    from app.services.analytics.consumption import get_consumption_stats_async
    from app.services.analytics.cost import get_cost_summary_async
    from app.services.analytics.forecast import get_expense_forecast_async

    db = real_async_db_session
    await _a_pantry_and_two_laptops(db, async_test_user, async_test_storage_location)
    org_id = async_test_user.organization_id

    cost = await get_cost_summary_async(db, org_id)
    forecast = await get_expense_forecast_async(db, org_id)
    alerts = await get_smart_alerts_async(db, org_id)
    patterns = await get_purchase_patterns_async(db, org_id)
    consumption = await get_consumption_stats_async(db, org_id)

    assert cost.total_spent == pytest.approx(10.0)
    assert sum(m.spent for m in cost.monthly_trend) == pytest.approx(10.0)
    assert 'Laptop' not in {c.category_name for c in cost.top_expensive_categories}
    assert sum(c.total_spent for c in cost.top_expensive_categories) == 10.0
    assert 'Laptop' not in {c.category_name for c in forecast.top_cost_drivers}
    alerted = {a['item_name'] for a in alerts['alerts']}
    assert 'Rice' in alerted
    assert 'Family laptop' not in alerted
    recurring = {p['name'] for p in patterns['top_recurring_products']}
    assert recurring == {'Rice'}
    assert {c.name for c in consumption.most_consumed} == {'Rice'}

    # With module data shown, the laptop is counted here as everywhere.
    await _show_module_data(db, async_test_user, True)
    cost = await get_cost_summary_async(db, org_id)
    patterns = await get_purchase_patterns_async(db, org_id)
    alerts = await get_smart_alerts_async(db, org_id)
    consumption = await get_consumption_stats_async(db, org_id)
    assert cost.total_spent == pytest.approx(6010.0)
    assert {c.name for c in consumption.most_consumed} == {'Rice', 'Family laptop'}
    assert 'Laptop' in {c.category_name for c in cost.top_expensive_categories}
    assert 'Family laptop' in {p['name'] for p in patterns['top_recurring_products']}
    assert 'Family laptop' in {a['item_name'] for a in alerts['alerts']}
