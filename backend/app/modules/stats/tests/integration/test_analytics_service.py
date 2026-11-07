"""
Integration tests for stats module AnalyticsServiceAsync.

Tests verify business logic for:
- Inventory rotation analysis
- Smart alerts and recommendations
- Expense forecasting
- Purchase pattern analysis
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stats.services import (
    get_expense_forecast,
    get_purchase_patterns_async,
    get_smart_alerts_async,
)
from app.services.analytics.forecast import _MIN_WEEKS_FOR_FORECAST
from tests.integration._purchases import purchase_template, receipt_layer
from tests.integration._shelf import put_on_shelf


@pytest.mark.integration
@pytest.mark.asyncio
class TestStatsAnalyticsService:
    """Test suite for AnalyticsServiceAsync."""

    async def test_rotation_analysis_empty_inventory(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        """Test rotation analysis with no items."""
        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, async_test_household.id
        )

        # Nothing on any shelf: there is no age to report, and None is how
        # the report says so — 0.0 days would read as the best possible age.
        assert result.average_stock_age_days is None
        assert result.median_stock_age_days is None
        assert result.slow_movers_count == 0
        assert result.dead_stock_count == 0
        assert result.slow_movers == []
        assert result.dead_stock == []

    async def test_rotation_analysis_with_active_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test rotation analysis with items stored for various durations."""
        items = []

        item1 = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Fresh Item',
            quantity=Decimal('1'),
            added_date=date.today() - timedelta(days=10),
            purchase_price=Decimal('10.00'),
        )
        items.append(item1)

        item2 = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Slow Mover',
            quantity=Decimal('2'),
            added_date=date.today() - timedelta(days=45),
            purchase_price=Decimal('25.00'),
        )
        items.append(item2)

        item3 = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Dead Stock',
            quantity=Decimal('1'),
            added_date=date.today() - timedelta(days=120),
            purchase_price=Decimal('50.00'),
        )
        items.append(item3)

        for item in items:
            real_async_db_session.add(item)
        await real_async_db_session.flush()

        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, async_test_household.id
        )

        assert result.average_stock_age_days == 58.3
        assert result.median_stock_age_days == 45.0
        assert result.slow_movers_count == 1
        assert result.dead_stock_count == 1
        assert len(result.slow_movers) == 1
        assert len(result.dead_stock) == 1
        assert result.dead_stock[0].name == 'Dead Stock'
        assert result.dead_stock_value == 50.0

    async def test_rotation_analysis_by_category(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """Test rotation analysis breakdown by category."""
        cat_meat = Category(name='Meat', icon='🥩', sort_order=1)
        cat_dairy = Category(name='Dairy', icon='🧀', sort_order=2)
        real_async_db_session.add_all([cat_meat, cat_dairy])
        await real_async_db_session.flush()

        for cat in [cat_meat, cat_dairy]:
            item = Item(
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                category_id=cat.id,
                name=f'{cat.name} Product',
                quantity=Decimal('1'),
                added_date=date.today() - timedelta(days=20),
                purchase_price=Decimal('15.00'),
            )
            real_async_db_session.add(item)
        await real_async_db_session.flush()

        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, async_test_household.id
        )

        assert len(result.rotation_by_category) == 2
        categories = {cat.category_name for cat in result.rotation_by_category}
        assert 'Meat' in categories
        assert 'Dairy' in categories

    async def test_smart_alerts_forgotten_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test detection of forgotten items (untouched for >60 days).

        An item with updated_at = now() is NOT forgotten, even if
        added_date is old. We backdate updated_at to simulate true neglect.
        """
        old_ts = datetime.combine(
            date.today() - timedelta(days=75), datetime.min.time()
        )
        forgotten = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Forgotten Item',
            quantity=Decimal('1'),
            added_date=date.today() - timedelta(days=75),
            updated_at=old_ts,
            created_at=old_ts,
        )

        recent_ts = datetime.combine(
            date.today() - timedelta(days=10), datetime.min.time()
        )
        recent = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Recent Item',
            quantity=Decimal('1'),
            added_date=date.today() - timedelta(days=10),
            updated_at=recent_ts,
            created_at=recent_ts,
        )

        real_async_db_session.add_all([forgotten, recent])
        await real_async_db_session.flush()

        result = await get_smart_alerts_async(
            real_async_db_session, async_test_household.id
        )

        forgotten_alerts = [
            a for a in result.get('alerts', []) if a.get('type') == 'FORGOTTEN_ITEM'
        ]
        assert len(forgotten_alerts) >= 1
        assert any('Forgotten Item' in a.get('item_name', '') for a in forgotten_alerts)

    async def test_smart_alerts_expiring_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test detection of items expiring soon (within 7 days)."""
        expiring_soon = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Expiring Soon',
            quantity=Decimal('1'),
            expiry_date=date.today() + timedelta(days=3),
        )

        expired = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Expired',
            quantity=Decimal('1'),
            expiry_date=date.today() - timedelta(days=1),
        )

        safe = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Safe',
            quantity=Decimal('1'),
            expiry_date=date.today() + timedelta(days=30),
        )

        real_async_db_session.add_all([expiring_soon, expired, safe])
        await real_async_db_session.flush()

        result = await get_smart_alerts_async(
            real_async_db_session, async_test_household.id
        )

        expiry_alerts = [
            a for a in result.get('alerts', []) if a.get('type') == 'EXPIRING_SOON'
        ]
        assert len(expiry_alerts) >= 1

    async def test_smart_alerts_name_the_expired_record_too(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """An expired record is the most urgent alert, not one left out.

        The overview counts it among what needs attention; the alerts beside
        it used to stop at today and never named the one item already spoiled.
        Each expiry alert leads to its record.
        """
        today = await core_api.organizations.today_async(
            real_async_db_session, async_test_household.id
        )
        cheddar = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Cheddar',
            quantity=Decimal('1'),
            expiry_date=today - timedelta(days=2),
        )
        milk = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Milk',
            quantity=Decimal('1'),
            expiry_date=today + timedelta(days=2),
        )
        real_async_db_session.add_all([cheddar, milk])
        await real_async_db_session.flush()

        result = await get_smart_alerts_async(
            real_async_db_session, async_test_household.id
        )

        expired = [a for a in result['alerts'] if a['type'] == 'EXPIRED']
        assert [a['item_name'] for a in expired] == ['Cheddar']
        assert expired[0]['severity'] == 'critical'
        assert expired[0]['message_key'] == 'stats.alerts.expired'
        assert expired[0]['expiry_date'] == (today - timedelta(days=2)).isoformat()
        assert expired[0]['action'] == 'view_item'
        assert expired[0]['action_param'] == str(cheddar.id)
        assert result['total_alerts'] == len(result['alerts'])
        # The expiring milk is still its own alert, and not counted twice.
        soon = [a for a in result['alerts'] if a['type'] == 'EXPIRING_SOON']
        assert [a['item_name'] for a in soon] == ['Milk']

    async def test_two_alerts_of_one_product_on_one_date_say_where_each_one_is(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """Same product, same date, two shelves: the place tells them apart.

        Two records of oregano on two shelves, both going off on the same day,
        read the same sentence twice in the same colour; the reader could not
        tell which shelf to go to first. The batch is named where it has one.
        """
        from app.models.product_template import ProductTemplate
        from app.models.stock_lot import StockLot

        db = real_async_db_session
        today = await core_api.organizations.today_async(db, async_test_household.id)
        oregano = ProductTemplate(
            organization_id=async_test_household.id, name='Dried Oregano'
        )
        top, bottom = (
            StorageLocation(
                organization_id=async_test_household.id,
                created_by=async_test_user.id,
                name=name,
                usage='internal',
            )
            for name in ('Shelf A - Top', 'Shelf A - Bottom')
        )
        db.add_all([oregano, top, bottom])
        await db.flush()
        lot = StockLot(
            organization_id=async_test_household.id,
            product_template_id=oregano.id,
            name='OR-2611',
        )
        db.add(lot)
        await db.flush()
        for shelf, lot_id in ((top, lot.id), (bottom, None)):
            await put_on_shelf(
                db,
                async_test_user,
                oregano,
                shelf.id,
                1,
                lot_id=lot_id,
                expiry_date=today + timedelta(days=3),
            )
        await db.flush()

        result = await get_smart_alerts_async(db, async_test_household.id)

        oregano_alerts = sorted(
            (
                (a['location_name'], a['lot_name'])
                for a in result['alerts']
                if a['item_name'] == 'Dried Oregano' and a['type'] == 'EXPIRING_SOON'
            ),
            key=str,
        )
        assert oregano_alerts == [
            ('Shelf A - Bottom', None),
            ('Shelf A - Top', 'OR-2611'),
        ]

    async def test_smart_alerts_leave_out_what_is_off_the_shelves(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """A record used up into a virtual place is no expiry alert.

        Consuming the last unit files a record under a non-internal place; its
        old date must not raise an "expired" alert for ever after.
        """
        today = await core_api.organizations.today_async(
            real_async_db_session, async_test_household.id
        )
        consumed = StorageLocation(
            organization_id=async_test_household.id,
            name='Consumed',
            usage='customer',
            created_by=async_test_storage_location.created_by,
        )
        real_async_db_session.add(consumed)
        await real_async_db_session.flush()
        real_async_db_session.add(
            Item(
                organization_id=async_test_household.id,
                storage_location_id=consumed.id,
                category_id=async_test_category.id,
                name='Eaten yogurt',
                quantity=Decimal('0'),
                expiry_date=today - timedelta(days=5),
            )
        )
        await real_async_db_session.flush()

        result = await get_smart_alerts_async(
            real_async_db_session, async_test_household.id
        )

        assert not [a for a in result['alerts'] if a['item_name'] == 'Eaten yogurt']

    async def test_smart_alerts_low_stock(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test detection of low stock items is handled by alerts (if implemented)."""
        low_stock = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Low Stock Item',
            quantity=Decimal('0.2'),
        )

        real_async_db_session.add(low_stock)
        await real_async_db_session.flush()

        result = await get_smart_alerts_async(
            real_async_db_session, async_test_household.id
        )

        assert 'alerts' in result
        assert 'total_alerts' in result
        assert isinstance(result['alerts'], list)

    async def _seed_weekly_purchases(
        self,
        db: AsyncSession,
        organization: Organization,
        location: StorageLocation,
        category: Category | None,
        *,
        weeks: int,
        price: str = '10.00',
        prefix: str = 'Purchase',
    ) -> None:
        """One purchase a week, `weeks` weeks back from today.

        A record for the shelf and a receipt layer for the ledger: the
        forecast reads the layers, the category drivers read the records.
        """
        template = purchase_template(organization.id, prefix)
        db.add(template)
        await db.flush()
        for i in range(weeks):
            on = date.today() - timedelta(days=7 * i)
            db.add(
                Item(
                    organization_id=organization.id,
                    storage_location_id=location.id,
                    category_id=category.id if category else None,
                    name=f'{prefix} {i}',
                    quantity=Decimal('1'),
                    purchase_price=Decimal(price),
                    created_at=on,
                )
            )
            db.add(receipt_layer(organization.id, template.id, value=price, on=on))
        await db.flush()

    async def test_expense_forecast_basic(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test expense forecasting with purchase history."""
        await self._seed_weekly_purchases(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            async_test_category,
            weeks=8,
        )

        result = await get_expense_forecast(
            real_async_db_session, async_test_household.id, 'month'
        )

        assert result.forecast_period == 'month'
        assert result.historical_avg > 0
        assert result.trend in ('stable', 'increasing', 'decreasing')
        assert result.weeks_of_data == 8
        assert result.confidence > 0

    async def test_expense_forecast_refuses_a_rate_it_cannot_read(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """A warehouse entered in one day is not a month of shopping.

        Averaging only the weeks that happen to hold a purchase turned a
        single day of intake into a permanent weekly rate — 583 seeded items
        read as a six-figure monthly spend on the day the account was opened.
        """
        template = purchase_template(async_test_household.id, 'Imported')
        real_async_db_session.add(template)
        await real_async_db_session.flush()
        for i in range(50):
            real_async_db_session.add(
                Item(
                    organization_id=async_test_household.id,
                    storage_location_id=async_test_storage_location.id,
                    category_id=async_test_category.id,
                    name=f'Imported {i}',
                    quantity=Decimal('1'),
                    purchase_price=Decimal('400.00'),
                    created_at=date.today(),
                )
            )
            real_async_db_session.add(
                receipt_layer(
                    async_test_household.id,
                    template.id,
                    value='400.00',
                    on=date.today(),
                )
            )
        await real_async_db_session.flush()

        result = await get_expense_forecast(
            real_async_db_session, async_test_household.id, 'month'
        )

        assert result.trend == 'no_data'
        assert result.predicted_spending == 0.0
        assert result.historical_avg == 0.0
        assert result.confidence == 0.0
        assert result.weeks_of_data == 1
        assert result.weeks_required == _MIN_WEEKS_FOR_FORECAST

    async def test_expense_forecast_confidence_follows_the_history(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Confidence measures the forecast, not the waste next to it.

        It used to be ``0.8 if annual_savings > 0`` — the potential for
        halving waste, which is why a six-figure prediction stood next to a
        bar reading 0%. Neither organization here wastes anything, so the
        only thing separating them is how long each has been observed.
        """
        longer_org = Organization(name='Longer History Org')
        real_async_db_session.add(longer_org)
        await real_async_db_session.flush()
        longer_location = StorageLocation(
            organization_id=longer_org.id,
            name='Cold Storage',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(longer_location)
        await real_async_db_session.flush()

        await self._seed_weekly_purchases(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            async_test_category,
            weeks=6,
            prefix='Short',
        )
        await self._seed_weekly_purchases(
            real_async_db_session,
            longer_org,
            longer_location,
            None,
            weeks=12,
            prefix='Long',
        )

        short = await get_expense_forecast(
            real_async_db_session, async_test_household.id, 'month'
        )
        longer = await get_expense_forecast(
            real_async_db_session, longer_org.id, 'month'
        )

        assert short.waste_reduction_potential == longer.waste_reduction_potential
        assert longer.confidence > short.confidence

    async def test_expense_forecast_counts_a_quiet_week_as_zero(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """A fortnightly shopper is not a weekly one.

        Every other week empty: averaged over the weeks that hold a purchase
        the rate comes out double what was actually spent.
        """
        template = purchase_template(async_test_household.id, 'Fortnightly')
        real_async_db_session.add(template)
        await real_async_db_session.flush()
        for i in range(0, 12, 2):
            on = date.today() - timedelta(days=7 * i)
            real_async_db_session.add(
                Item(
                    organization_id=async_test_household.id,
                    storage_location_id=async_test_storage_location.id,
                    category_id=async_test_category.id,
                    name=f'Fortnightly {i}',
                    quantity=Decimal('1'),
                    purchase_price=Decimal('100.00'),
                    created_at=on,
                )
            )
            real_async_db_session.add(
                receipt_layer(
                    async_test_household.id, template.id, value='100.00', on=on
                )
            )
        await real_async_db_session.flush()

        result = await get_expense_forecast(
            real_async_db_session, async_test_household.id, 'month'
        )

        # Six purchases of 100 across eleven weeks — about 54.5 a week, not
        # the 100 a week the non-empty buckets alone would report.
        assert result.weeks_of_data == 11
        assert 50 < result.historical_avg / 4.33 < 60

    async def test_purchase_patterns_basic(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test purchase pattern analysis."""
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Milk',
            quantity=Decimal('1'),
            purchase_price=Decimal('4.99'),
        )
        real_async_db_session.add(item)
        await real_async_db_session.flush()

        for week in range(4):
            history = ItemHistory(
                organization_id=async_test_household.id,
                item_id=item.id,
                user_id=async_test_user.id,
                action='USED',
                created_at=date.today() - timedelta(days=7 * week),
            )
            real_async_db_session.add(history)
        await real_async_db_session.flush()

        result = await get_purchase_patterns_async(
            real_async_db_session, async_test_household.id
        )

        assert result is not None
        assert isinstance(result, dict)

    async def test_rotation_analysis_ignores_deleted_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test that deleted items are excluded from analysis."""
        deleted_item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Deleted Item',
            quantity=Decimal('1'),
            added_date=date.today() - timedelta(days=90),
            is_deleted=True,
        )

        active_item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Active Item',
            quantity=Decimal('1'),
            added_date=date.today() - timedelta(days=10),
            is_deleted=False,
        )

        real_async_db_session.add_all([deleted_item, active_item])
        await real_async_db_session.flush()

        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, async_test_household.id
        )

        assert result.average_stock_age_days == 10.0
        assert result.dead_stock_count == 0
        assert len(result.dead_stock) == 0

    # A test for items without added_date lived here once. The column is
    # NOT NULL and the model defaults it on insert, so an undated row is
    # unrepresentable — the aging query's isnot(None) guard is for a state
    # the schema forbids. "No measurable age" is the empty-shelf case, and
    # it is pinned by test_rotation_analysis_with_no_items above, which now
    # answers None.

    async def test_smart_alerts_multiple_types(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test that smart alerts detects multiple alert types together."""
        old_ts = datetime.combine(
            date.today() - timedelta(days=90), datetime.min.time()
        )
        forgotten = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Forgotten Item',
            quantity=Decimal('1'),
            added_date=date.today() - timedelta(days=90),
            updated_at=old_ts,
            created_at=old_ts,
            expiry_date=date.today() - timedelta(days=5),
        )

        expiring_soon = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Expiring Soon',
            quantity=Decimal('1'),
            expiry_date=date.today() + timedelta(days=2),
        )

        real_async_db_session.add_all([forgotten, expiring_soon])
        await real_async_db_session.flush()

        result = await get_smart_alerts_async(
            real_async_db_session, async_test_household.id
        )

        alerts = result.get('alerts', [])
        assert len(alerts) >= 2
        alert_types = {a.get('type') for a in alerts}
        assert 'FORGOTTEN_ITEM' in alert_types or 'EXPIRING_SOON' in alert_types

    async def test_rotation_analysis_value_calculations(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        async_test_category: Category,
    ) -> None:
        """Test that value calculations are correct."""
        items_data = [
            ('Item 1', 30.0, 100.00),
            ('Item 2', 45.0, 50.00),
            ('Item 3', 95.0, 200.00),
        ]

        for name, days, price in items_data:
            item = Item(
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                category_id=async_test_category.id,
                name=name,
                quantity=Decimal('1'),
                added_date=date.today() - timedelta(days=int(days)),
                purchase_price=Decimal(str(price)),
            )
            real_async_db_session.add(item)
        await real_async_db_session.flush()

        result = await core_api.queries.get_rotation_analysis_async(
            real_async_db_session, async_test_household.id
        )

        assert result.slow_movers_value == 50.0
        assert result.dead_stock_value == 200.0
        assert result.dead_stock_count == 1
        assert result.slow_movers_count == 1
