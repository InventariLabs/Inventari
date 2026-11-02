"""Performance regression tests for the equipment dashboard.

Before the fix the dashboard read the whole fleet up to three times per
request and issued one assignment query per warranty candidate (N+1):

- ``get_dashboard`` fetched items, then ``get_warranty_alerts`` fetched
  them again and queried assignments per item.
- ``get_fleet_valuation_async`` issued one items query per equipment
  category (``limit=5000`` each) and computed everything uncached.

After the fix:

- ``get_warranty_alerts`` accepts a pre-fetched item list and resolves
  active assignments with ONE batch query, regardless of candidate count.
- ``get_dashboard`` passes its already-fetched items down.
- ``get_fleet_valuation_async`` fetches equipment items with a single
  ``context_tag`` query and caches the result for 60 seconds.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_module
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment.dashboard_service import (
    _get_equipment_items_and_categories_async,
    get_dashboard,
    get_expired_warranty_alerts,
    get_warranty_alerts,
)
from app.modules.equipment.depreciation_service import get_fleet_valuation_async
from app.modules.equipment.models import EquipmentAssignment
from tests.integration._fake_redis import FakeRedis

pytestmark = pytest.mark.integration

_ASSET_COUNT = 12


# ---------------------------------------------------------------------------
# Query counter: register a before_cursor_execute listener that increments
# a counter for every statement the session issues.
# ---------------------------------------------------------------------------


class _QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0


@pytest.fixture
def query_counter() -> _QueryCounter:
    return _QueryCounter()


@pytest.fixture
def track_queries(
    real_async_db_session: AsyncSession, query_counter: _QueryCounter
) -> Iterator[None]:
    """Counts every SQL statement issued through the test's engine."""
    bind = real_async_db_session.get_bind()

    def before_cursor_execute(*_args: Any, **_kwargs: Any) -> None:
        query_counter.count += 1

    event.listen(bind, 'before_cursor_execute', before_cursor_execute)
    try:
        yield
    finally:
        event.remove(bind, 'before_cursor_execute', before_cursor_execute)


@pytest.fixture(autouse=True)
def _reset_cache_redis() -> Iterator[None]:
    """Restore the cache module to its unconfigured state around each test."""
    original = cache_module._redis
    yield
    cache_module._redis = original


# ---------------------------------------------------------------------------
# Async fixtures: org + user + location + categories + assets with warranties.
# ---------------------------------------------------------------------------


@pytest.fixture
async def dash_org(real_async_db_session: AsyncSession) -> Organization:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(
        name=f'Bounds Org {suffix}',
        enabled_modules=['core', 'items', 'equipment'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def dash_user(
    real_async_db_session: AsyncSession, dash_org: Organization
) -> User:
    user = User(
        email=f'dash-{uuid.uuid4().hex[:8]}@test.example',
        hashed_password='x',
        full_name='Bounds User',
        organization_id=dash_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def dash_location(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_user: User,
) -> StorageLocation:
    storage_type = StorageType(
        name='IT Storage', type_code='IT_STORAGE', behavior_mode='NONE'
    )
    real_async_db_session.add(storage_type)
    await real_async_db_session.flush()
    location = StorageLocation(
        name='Server Room',
        organization_id=dash_org.id,
        storage_type_id=storage_type.id,
        created_by=dash_user.id,
    )
    real_async_db_session.add(location)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(location)
    return location


async def _make_category(db: AsyncSession, *, name: str, code: str) -> Category:
    category = Category(
        name=name,
        code=code,
        context_tag='equipment',
        organization_id=None,
        field_definitions=[],
    )
    db.add(category)
    await db.flush()
    await db.refresh(category)
    return category


@pytest.fixture
async def dash_categories(real_async_db_session: AsyncSession) -> list[Category]:
    return [
        await _make_category(real_async_db_session, name='Laptop', code='LAPTOP'),
        await _make_category(real_async_db_session, name='Monitor', code='MONITOR'),
    ]


async def _make_asset(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    category: Category,
    *,
    name: str,
    warranty_until: date,
) -> Item:
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        purchase_price=Decimal('1000.00'),
        meta_data={
            'equipment': {
                'equipment_status': 'AVAILABLE',
                'warranty_until': warranty_until.isoformat(),
            }
        },
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@pytest.fixture
async def dash_assets(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_location: StorageLocation,
    dash_categories: list[Category],
    dash_user: User,
) -> list[Item]:
    """12 assets with warranties inside the 30-day window; 6 checked out."""
    window_date = date.today() + timedelta(days=10)
    laptop_cat, monitor_cat = dash_categories
    assets: list[Item] = []
    for i in range(_ASSET_COUNT):
        category = laptop_cat if i % 2 == 0 else monitor_cat
        item = await _make_asset(
            real_async_db_session,
            dash_org,
            dash_location,
            category,
            name=f'Bounds Asset {i}',
            warranty_until=window_date,
        )
        if i < 6:
            real_async_db_session.add(
                EquipmentAssignment(
                    organization_id=dash_org.id,
                    item_id=item.id,
                    assigned_to_name=f'Assignee {i}',
                    checked_out_by=dash_user.id,
                    checked_out_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
        assets.append(item)
    await real_async_db_session.commit()
    return assets


# ---------------------------------------------------------------------------
# Regression tests: query counts are bounded.
# ---------------------------------------------------------------------------


async def test_warranty_alerts_uses_one_batch_query(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_assets: list[Item],
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """get_warranty_alerts must not issue one assignment query per item."""
    query_counter.reset()

    alerts = await get_warranty_alerts(real_async_db_session, dash_org.id, days=30)

    assert len(alerts) == _ASSET_COUNT
    by_item = {a.item_id: a for a in alerts}
    for item in dash_assets:
        alert = by_item[item.id]
        if int(item.name.rsplit(' ', 1)[1]) < 6:
            assert alert.assigned_to is not None
        else:
            assert alert.assigned_to is None
    # categories (1) + items (1 + 4 selectinloads) + assignments batch (1) <= 10
    assert query_counter.count <= 10, (
        f'Expected <= 10 queries, got {query_counter.count}. N+1 regression detected.'
    )


async def test_a_deployed_asset_names_the_place_on_its_warranty_alert(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_location: StorageLocation,
    dash_categories: list[Category],
    dash_user: User,
    track_queries: None,
) -> None:
    """The alert row's "where" slot answers who or what holds the asset, and
    for a deployment that is the place — the same answer the overdue row
    gives, from the same one definition."""
    item = await _make_asset(
        real_async_db_session,
        dash_org,
        dash_location,
        dash_categories[0],
        name='Bounds Deployed',
        warranty_until=date.today() + timedelta(days=10),
    )
    real_async_db_session.add(
        EquipmentAssignment(
            organization_id=dash_org.id,
            item_id=item.id,
            assigned_to_name='',
            checkout_location_id=dash_location.id,
            checked_out_by=dash_user.id,
            checked_out_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await real_async_db_session.commit()

    alerts = await get_warranty_alerts(real_async_db_session, dash_org.id, days=30)

    alert = next(a for a in alerts if a.item_id == item.id)
    assert alert.assigned_to == dash_location.name


async def test_warranty_alerts_prefetched_items_skip_refetch(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_assets: list[Item],
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """With items passed in, only the batch assignment query may run."""
    eq_items, cat_by_id = await _get_equipment_items_and_categories_async(
        real_async_db_session, dash_org.id
    )
    query_counter.reset()

    alerts = await get_warranty_alerts(
        real_async_db_session,
        dash_org.id,
        days=30,
        items=eq_items,
        cat_by_id=cat_by_id,
    )

    assert len(alerts) == _ASSET_COUNT
    assert query_counter.count <= 2, (
        f'Expected <= 2 queries with prefetched items, got {query_counter.count}.'
    )


async def test_dashboard_passes_items_down_and_bounds_queries(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_assets: list[Item],
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """get_dashboard reuses its item fetch for warranty alerts."""
    query_counter.reset()

    dashboard = await get_dashboard(real_async_db_session, dash_org.id)

    assert dashboard.total_assets == _ASSET_COUNT
    assert len(dashboard.warranty_alerts) == _ASSET_COUNT
    assert query_counter.count < 20, (
        f'Expected < 20 queries, got {query_counter.count}. '
        'Dashboard still re-fetches the fleet or issues per-item queries.'
    )


async def test_fleet_valuation_single_fetch_and_cached(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_assets: list[Item],
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """Valuation fetches items once and serves the second call from cache."""
    fake_redis = FakeRedis()
    cache_module._redis = fake_redis  # type: ignore[assignment]

    query_counter.reset()
    first = await get_fleet_valuation_async(real_async_db_session, dash_org.id)
    first_queries = query_counter.count
    # Items fetch + selectinloads + org currency + module settings +
    # category field definitions (one change merged on top of another); still a
    # bounded set — no per-category loops.
    assert first_queries <= 10, (
        f'Expected <= 10 queries for valuation, got {first_queries}. '
        'Valuation still fetches per category.'
    )

    query_counter.reset()
    second = await get_fleet_valuation_async(real_async_db_session, dash_org.id)

    assert query_counter.count == 0, 'Cached valuation must not hit the database.'
    assert second == first
    # Decimal values survive the JSON cache round-trip
    for category_row in second.by_category:
        assert isinstance(category_row.purchase_value, Decimal)


# ---------------------------------------------------------------------------
# follow-up (audit 2026-08-16): the "already out of warranty" section
# added by was left out of the batching pass. The fixtures above give
# every asset a warranty inside the window, so the expired branch never ran
# and the bound tests could not see its per-item queries. These tests give
# the fleet expired warranties instead, and — more importantly — compare the
# query count across two fleet sizes, which is the only way a fixed
# threshold cannot hide an O(N) loop.
# ---------------------------------------------------------------------------


async def _seed_expired_fleet(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    categories: list[Category],
    user: User,
    count: int,
    *,
    prefix: str,
) -> None:
    expired_date = date.today() - timedelta(days=90)
    laptop_cat, monitor_cat = categories
    for i in range(count):
        item = await _make_asset(
            db,
            org,
            location,
            laptop_cat if i % 2 == 0 else monitor_cat,
            name=f'{prefix} {i}',
            warranty_until=expired_date,
        )
        if i % 3 == 0:
            db.add(
                EquipmentAssignment(
                    organization_id=org.id,
                    item_id=item.id,
                    assigned_to_name=f'{prefix} holder {i}',
                    checked_out_by=user.id,
                    checked_out_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
    await db.commit()


async def test_expired_warranty_alerts_do_not_scale_with_fleet_size(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_location: StorageLocation,
    dash_categories: list[Category],
    dash_user: User,
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """Doubling the fleet must not double the number of queries."""
    await _seed_expired_fleet(
        real_async_db_session,
        dash_org,
        dash_location,
        dash_categories,
        dash_user,
        count=6,
        prefix='Bounds Expired A',
    )

    query_counter.reset()
    small = await get_expired_warranty_alerts(real_async_db_session, dash_org.id)
    small_queries = query_counter.count
    assert len(small) == 6

    await _seed_expired_fleet(
        real_async_db_session,
        dash_org,
        dash_location,
        dash_categories,
        dash_user,
        count=12,
        prefix='Bounds Expired B',
    )

    query_counter.reset()
    large = await get_expired_warranty_alerts(real_async_db_session, dash_org.id)
    large_queries = query_counter.count
    assert len(large) == 18

    assert large_queries == small_queries, (
        f'Expired-warranty alerts issue {small_queries} queries for 6 assets '
        f'and {large_queries} for 18 — still one query per item.'
    )
    assert any(a.assigned_to for a in large), (
        'Batched lookup must still resolve who holds an expired-warranty asset.'
    )


async def test_expired_warranty_alerts_reuse_the_prefetched_fleet(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_location: StorageLocation,
    dash_categories: list[Category],
    dash_user: User,
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """Given the fleet, the expired section needs one assignment query."""
    await _seed_expired_fleet(
        real_async_db_session,
        dash_org,
        dash_location,
        dash_categories,
        dash_user,
        count=8,
        prefix='Bounds Expired C',
    )
    items, cat_by_id = await _get_equipment_items_and_categories_async(
        real_async_db_session, dash_org.id
    )

    query_counter.reset()
    alerts = await get_expired_warranty_alerts(
        real_async_db_session, dash_org.id, items=items, cat_by_id=cat_by_id
    )

    assert len(alerts) == 8
    assert query_counter.count <= 2, (
        f'Expected <= 2 queries with a prefetched fleet, got {query_counter.count}.'
    )


async def test_dashboard_fetches_the_fleet_once_with_expired_warranties(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_location: StorageLocation,
    dash_categories: list[Category],
    dash_user: User,
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """The dashboard's query count is flat across fleet sizes."""
    await _seed_expired_fleet(
        real_async_db_session,
        dash_org,
        dash_location,
        dash_categories,
        dash_user,
        count=6,
        prefix='Bounds Dash A',
    )

    query_counter.reset()
    await get_dashboard(real_async_db_session, dash_org.id)
    small_queries = query_counter.count

    await _seed_expired_fleet(
        real_async_db_session,
        dash_org,
        dash_location,
        dash_categories,
        dash_user,
        count=12,
        prefix='Bounds Dash B',
    )

    query_counter.reset()
    dashboard = await get_dashboard(real_async_db_session, dash_org.id)
    large_queries = query_counter.count

    assert len(dashboard.expired_warranty_alerts) == 18
    assert large_queries == small_queries, (
        f'Dashboard issues {small_queries} queries for 6 assets and '
        f'{large_queries} for 18 — a per-item query survived.'
    )


async def test_retired_but_still_assigned_counts_once(
    real_async_db_session: AsyncSession,
    dash_org: Organization,
    dash_location: StorageLocation,
    dash_categories: list[Category],
    dash_user: User,
    track_queries: None,
) -> None:
    """Legacy rows written before the guard must not double-count.

       Retiring a checked-out asset is refused now, but assets retired while
       assigned already exist in older databases. The dashboard counts such an
    asset as issued — the same rule applied to MAINTENANCE.
    """
    item = await _make_asset(
        real_async_db_session,
        dash_org,
        dash_location,
        dash_categories[0],
        name='Bounds Retired while assigned',
        warranty_until=date.today() + timedelta(days=10),
    )
    meta = dict(item.meta_data or {})
    meta['equipment'] = {**meta.get('equipment', {}), 'equipment_status': 'RETIRED'}
    item.meta_data = meta
    real_async_db_session.add(
        EquipmentAssignment(
            organization_id=dash_org.id,
            item_id=item.id,
            assigned_to_name='Anna Kowalska',
            checked_out_by=dash_user.id,
            checked_out_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await real_async_db_session.commit()

    dashboard = await get_dashboard(real_async_db_session, dash_org.id)

    assert dashboard.retired == 0
    assert dashboard.by_status.get('RETIRED', 0) == 0
    assert dashboard.by_status.get('DEPLOYED', 0) == 1
    assert dashboard.active_assignments == 1
