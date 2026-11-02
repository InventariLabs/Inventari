"""Statistics built from an arbitrary five hundred rows are not statistics.

Rotation and the expense forecast both carried ``_MAX_ROWS = 500`` and
applied it to queries that then had their averages, medians and rankings
computed in Python. Some of those queries had no ORDER BY at all, so past
five hundred rows the figure came from whichever subset the database
happened to return -- and could differ between two identical requests. The
ones that were ordered were worse in a quieter way: taking the five hundred
youngest items and reporting their median as the median, or the five hundred
newest purchases and reading the resulting slope as a rising trend.

Each test below builds six hundred rows whose true answer is known, and
asserts the true answer. Under the truncation none of them can be right.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from tests.integration._purchases import purchase_template

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Comfortably past the old cap, so every truncation shows.
_ROWS = 600

#: Ages 1..600 days, so the true mean and the true median are both 300.5.
_TRUE_AVERAGE = 300.5


async def _organization(
    db: AsyncSession,
) -> tuple[Organization, StorageLocation]:
    from app.core.testing import ModuleTestHelper

    org = Organization(
        name=f'Analytics {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'stats'],
        currency='EUR',
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'analytics_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid.uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.flush()
    return org, location


@pytest.fixture
async def aged_shelf(real_async_db_session: AsyncSession) -> Organization:
    """Six hundred records aged one to six hundred days, each one consumed.

    The same ladder answers both halves of rotation: how long what is here
    has been here, and how long what left had been here when it went.
    """
    db = real_async_db_session
    org, location = await _organization(db)
    today = date.today()

    items = []
    history = []
    for age in range(1, _ROWS + 1):
        item_id = uuid.uuid4()
        items.append(
            {
                'id': item_id,
                'name': f'Item {age}',
                'organization_id': org.id,
                'storage_location_id': location.id,
                'quantity': Decimal('1'),
                'added_date': today - timedelta(days=age),
                'is_deleted': False,
            }
        )
        history.append(
            {
                'id': uuid.uuid4(),
                'organization_id': org.id,
                'item_id': item_id,
                'action': 'USED',
                'created_at': datetime.now(UTC),
            }
        )

    await db.execute(Item.__table__.insert(), items)
    await db.execute(ItemHistory.__table__.insert(), history)
    await db.commit()
    return org


class TestHowLongThingsHaveBeenHere:
    async def test_the_average_counts_every_record(
        self, real_async_db_session: AsyncSession, aged_shelf: Organization
    ) -> None:
        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, aged_shelf.id
        )
        assert result.average_stock_age_days == _TRUE_AVERAGE

    async def test_the_median_counts_every_record(
        self, real_async_db_session: AsyncSession, aged_shelf: Organization
    ) -> None:
        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, aged_shelf.id
        )
        assert result.median_stock_age_days == _TRUE_AVERAGE


class TestHowLongThingsHadBeenHereWhenTheyLeft:
    async def test_the_average_counts_every_record(
        self, real_async_db_session: AsyncSession, aged_shelf: Organization
    ) -> None:
        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, aged_shelf.id
        )
        assert result.average_days_to_consume == _TRUE_AVERAGE

    async def test_the_median_counts_every_record(
        self, real_async_db_session: AsyncSession, aged_shelf: Organization
    ) -> None:
        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, aged_shelf.id
        )
        assert result.median_days_to_consume == _TRUE_AVERAGE


@pytest.fixture
async def two_kinds_of_spending(real_async_db_session: AsyncSession) -> Organization:
    """Many cheap purchases in one category, few expensive ones in another.

    Written cheap-first, because a truncation that keeps whichever rows come
    first would then never see the expensive category at all -- which is the
    ranking the report exists to show.
    """
    db = real_async_db_session
    org, location = await _organization(db)

    everyday = Category(name='Everyday', organization_id=org.id)
    machinery = Category(name='Machinery', organization_id=org.id)
    db.add_all([everyday, machinery])
    await db.flush()

    rows = []
    for index in range(550):
        rows.append(
            {
                'id': uuid.uuid4(),
                'name': f'Cheap {index}',
                'organization_id': org.id,
                'storage_location_id': location.id,
                'category_id': everyday.id,
                'quantity': Decimal('1'),
                'purchase_price': Decimal('1.00'),
                'currency': 'EUR',
                'is_deleted': False,
            }
        )
    for index in range(50):
        rows.append(
            {
                'id': uuid.uuid4(),
                'name': f'Dear {index}',
                'organization_id': org.id,
                'storage_location_id': location.id,
                'category_id': machinery.id,
                'quantity': Decimal('1'),
                'purchase_price': Decimal('100.00'),
                'currency': 'EUR',
                'is_deleted': False,
            }
        )
    await db.execute(Item.__table__.insert(), rows)
    await db.commit()
    return org


class TestWhatTheMoneyWentOn:
    async def test_the_dearest_category_leads(
        self, real_async_db_session: AsyncSession, two_kinds_of_spending: Organization
    ) -> None:
        result = await core_api.queries.get_expense_forecast_async(
            real_async_db_session, two_kinds_of_spending.id
        )
        assert result.top_cost_drivers, 'the report should name a category'
        assert result.top_cost_drivers[0].category_name == 'Machinery'
        assert result.top_cost_drivers[0].total_spent == 5000.00

    async def test_the_cheap_category_is_still_counted(
        self, real_async_db_session: AsyncSession, two_kinds_of_spending: Organization
    ) -> None:
        result = await core_api.queries.get_expense_forecast_async(
            real_async_db_session, two_kinds_of_spending.id
        )
        by_name = {c.category_name: c for c in result.top_cost_drivers}
        assert by_name['Everyday'].total_spent == 550.00
        assert by_name['Everyday'].items_count == 550


@pytest.fixture
async def a_steady_shopper(real_async_db_session: AsyncSession) -> Organization:
    """The same spend every week for twelve weeks, in six hundred purchases.

    Nothing about this is a trend. Keeping only the newest five hundred rows
    empties the oldest weeks, and the report reads its own truncation as a
    household spending more and more.
    """
    db = real_async_db_session
    org, location = await _organization(db)

    now = datetime.now(UTC)
    rows = []
    for week in range(12):
        week_start = now - timedelta(days=(week * 7) + 3)
        for purchase in range(50):
            rows.append(
                {
                    'id': uuid.uuid4(),
                    'name': f'Purchase {week}-{purchase}',
                    'organization_id': org.id,
                    'storage_location_id': location.id,
                    'quantity': Decimal('1'),
                    'purchase_price': Decimal('2.00'),
                    'currency': 'EUR',
                    'created_at': week_start,
                    'is_deleted': False,
                }
            )
    await db.execute(Item.__table__.insert(), rows)
    # The forecast reads the ledger: one receipt layer per purchase, dated
    # the same, worth the same.
    template = purchase_template(org.id)
    db.add(template)
    await db.flush()
    await db.execute(
        StockValuationLayer.__table__.insert(),
        [
            {
                'id': uuid.uuid4(),
                'organization_id': org.id,
                'product_template_id': template.id,
                'quantity': Decimal('1'),
                'remaining_qty': Decimal('1'),
                'unit_cost': Decimal('2.0000'),
                'total_value': Decimal('2.00'),
                'document_date': row['created_at'].date(),
                'currency': None,
                'direction': 'IN',
                'cost_basis': 'stated',
            }
            for row in rows
        ],
    )
    await db.commit()
    return org


class TestSpendingThatIsNotGoingAnywhere:
    async def test_the_trend_is_stable(
        self, real_async_db_session: AsyncSession, a_steady_shopper: Organization
    ) -> None:
        result = await core_api.queries.get_expense_forecast_async(
            real_async_db_session, a_steady_shopper.id
        )
        assert result.trend == 'stable', result.trend_percentage

    async def test_every_week_is_in_the_series(
        self, real_async_db_session: AsyncSession, a_steady_shopper: Organization
    ) -> None:
        result = await core_api.queries.get_expense_forecast_async(
            real_async_db_session, a_steady_shopper.id
        )
        assert result.weeks_of_data == 12
