"""Tests for core_api.queries — analytics read-models.

Verifies the Tier 1 named read-models exposed via the CoreAPI queries
namespace. These are domain-neutral aggregates (counts, sums, GROUP BY)
that modules consume instead of bypassing to app.models directly.

Contract:
    - Org-scoped: data from other organizations is never counted.
    - Read-only: no commit/add/delete (CoreAPI flush-only contract).
    - Returns neutral DTOs (OverviewDTO, etc.).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    ActivityDTO,
    CategoryCostDTO,
    CategoryStatsDTO,
    ConsumptionStatsDTO,
    CostSummaryDTO,
    ExpenseForecastDTO,
    ExpiryBucketDTO,
    OverviewDTO,
    ReconciliationDTO,
    RotationAnalysisDTO,
    StorageStatsDTO,
)
from app.core.public_api import core_api
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.product_template import ProductTemplate
from tests.integration._purchases import purchase_template, receipt_layer
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


async def _make_template(
    db: AsyncSession, org_id, *, name: str = 'Tpl', min_quantity: Decimal | None = None
) -> ProductTemplate:
    tpl = ProductTemplate(organization_id=org_id, name=name, min_quantity=min_quantity)
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    return tpl


async def _record_outflow(
    db: AsyncSession,
    item: Item,
    *,
    action: str,
    quantity,
    value,
) -> None:
    """Seed a use or a disposal the way the application records one.

    Both halves: the history row carries the quantity under ``qty`` — the key
    the consume and discard path writes — and the valuation ledger carries
    what it was worth, in an outgoing layer.

    These tests used to seed ``quantity_consumed``, ``consumed_cost``,
    ``quantity_discarded`` and ``wasted_cost``: four keys that exist nowhere
    else in the application, so they passed against a shape production never
    creates while the report itself read zero.
    """
    from app.models.product_template import ProductTemplate
    from app.models.stock_valuation_layer import StockValuationLayer

    if item.template_id is None:
        template = ProductTemplate(name=item.name, organization_id=item.organization_id)
        db.add(template)
        await db.flush()
        item.template_id = template.id

    db.add(
        ItemHistory(
            organization_id=item.organization_id,
            item_id=item.id,
            action=action,
            changes={'qty': float(quantity), 'old': float(item.quantity)},
        )
    )
    db.add(
        StockValuationLayer(
            organization_id=item.organization_id,
            product_template_id=item.template_id,
            item_id=item.id,
            quantity=Decimal(str(quantity)),
            remaining_qty=Decimal('0'),
            unit_cost=Decimal(str(value)) / Decimal(str(quantity)),
            total_value=Decimal(str(value)),
            direction='OUT',
            reason=action,
        )
    )
    await db.run_sync(anchor_pending_records)
    await db.commit()


async def _make_item(
    db: AsyncSession,
    org_id,
    storage_id,
    *,
    name: str = 'Item',
    quantity: Decimal = Decimal('5'),
    expiry_date: date | None = None,
    template_id=None,
    category_id=None,
    currency: str = 'USD',
    is_deleted: bool = False,
) -> Item:
    item = Item(
        organization_id=org_id,
        storage_location_id=storage_id,
        name=name,
        quantity=quantity,
        expiry_date=expiry_date,
        template_id=template_id,
        category_id=category_id,
        currency=currency,
        is_deleted=is_deleted,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


@pytest.mark.asyncio
class TestCoreQueriesOverview:
    """core_api.queries.get_overview_async."""

    async def test_empty_org_returns_zeros(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Org with no items → all counts zero, total_locations counts locations."""
        db = real_async_db_session
        result = await core_api.queries.get_overview_async(
            db, async_test_storage_location.organization_id
        )
        assert isinstance(result, OverviewDTO)
        assert result.total_items == 0
        assert result.expiring_soon == 0
        assert result.expired == 0
        assert result.low_stock == 0
        assert result.total_locations >= 1

    async def test_counts_items_and_expiry_buckets(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Items split correctly into total / expiring-soon / expired buckets."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        today = date.today()

        await _make_item(db, org_id, loc_id, name='Fresh')
        await _make_item(
            db, org_id, loc_id, name='Soon', expiry_date=today + timedelta(days=3)
        )
        await _make_item(
            db, org_id, loc_id, name='Expired', expiry_date=today - timedelta(days=1)
        )
        await db.commit()

        result = await core_api.queries.get_overview_async(db, org_id)

        assert result.total_items == 3
        assert result.expiring_soon == 1
        assert result.expired == 1

    async def test_deleted_items_excluded(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Soft-deleted items are not counted."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        await _make_item(db, org_id, loc_id, name='Alive')
        await _make_item(db, org_id, loc_id, name='Gone', is_deleted=True)
        await db.commit()

        result = await core_api.queries.get_overview_async(db, org_id)
        assert result.total_items == 1

    async def test_low_stock_detected_via_template_threshold(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """A product below ``ProductTemplate.min_quantity`` is one shortage.

        The threshold is one value per product, so what is compared with it
        is the product's stock, not each record of it: this used to count
        the five-unit record as a shortage while fifty-five units of the
        same staple sat on the shelves against a minimum of ten.
        """
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        tpl = await _make_template(
            db, org_id, name='Staple', min_quantity=Decimal('10')
        )
        await _make_item(
            db, org_id, loc_id, name='Low', quantity=Decimal('5'), template_id=tpl.id
        )
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Plenty',
            quantity=Decimal('50'),
            template_id=tpl.id,
        )
        await db.commit()

        result = await core_api.queries.get_overview_async(db, org_id)
        assert result.low_stock == 0

        # The other half, on the same shape of data: a total that really is
        # short counts once for the product, however many records hold it.
        short = await _make_template(
            db, org_id, name='Scarce', min_quantity=Decimal('10')
        )
        for name, quantity in (('a', '1'), ('b', '2'), ('c', '3')):
            await _make_item(
                db,
                org_id,
                loc_id,
                name=name,
                quantity=Decimal(quantity),
                template_id=short.id,
            )
        await db.commit()

        result = await core_api.queries.get_overview_async(db, org_id)
        assert result.low_stock == 1

    async def test_org_scoped_other_org_items_ignored(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
        async_test_user,
    ):
        """Items in a different organization's storage are never counted."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        await _make_item(db, org_id, loc_id, name='Ours')
        # Foreign org with its own storage location + item
        from app.models.organization import Organization
        from app.models.storage_location import StorageLocation

        foreign_org = Organization(name='Foreign Org')
        db.add(foreign_org)
        await db.flush()
        foreign_loc = StorageLocation(
            organization_id=foreign_org.id,
            name='Foreign',
            created_by=async_test_user.id,
        )
        db.add(foreign_loc)
        await db.flush()
        await _make_item(db, foreign_org.id, foreign_loc.id, name='Theirs')
        await db.commit()

        result = await core_api.queries.get_overview_async(db, org_id)
        assert result.total_items == 1


@pytest.mark.asyncio
class TestCoreQueriesStatsByStorage:
    """core_api.queries.get_stats_by_storage_async."""

    async def test_returns_per_location_counts(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Items are grouped by their storage location with correct counts."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        await _make_item(db, org_id, loc_id, name='A')
        await _make_item(db, org_id, loc_id, name='B')
        await db.commit()

        result = await core_api.queries.get_stats_by_storage_async(db, org_id)

        assert len(result) >= 1
        target = next(r for r in result if r.location_id == loc_id)
        assert isinstance(target, StorageStatsDTO)
        assert target.items_count == 2

    async def test_empty_org_returns_zero_counts(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Org with storages but no items returns rows with zero counts."""
        db = real_async_db_session
        result = await core_api.queries.get_stats_by_storage_async(
            db, async_test_storage_location.organization_id
        )
        assert isinstance(result, list)
        assert any(r.items_count == 0 for r in result)


@pytest.mark.asyncio
class TestCoreQueriesStatsByCategory:
    """core_api.queries.get_stats_by_category_async."""

    async def test_aggregates_items_per_category(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
        async_test_category,
    ):
        """Items group by category with summed stock value."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        await _make_item(
            db,
            org_id,
            loc_id,
            name='X',
            quantity=Decimal('2'),
            category_id=async_test_category.id,
        )
        await db.commit()

        result = await core_api.queries.get_stats_by_category_async(db, org_id)

        assert len(result) >= 1
        target = next(r for r in result if r.category_id == async_test_category.id)
        assert isinstance(target, CategoryStatsDTO)
        assert target.items_count == 1


@pytest.mark.asyncio
class TestCoreQueriesExpiryForecast:
    """core_api.queries.get_expiry_forecast_async."""

    async def test_six_buckets_returned(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Always returns exactly 6 named buckets, even if all zero."""
        db = real_async_db_session
        result = await core_api.queries.get_expiry_forecast_async(
            db, async_test_storage_location.organization_id
        )
        assert len(result) == 6
        periods = [b.period for b in result]
        assert periods == [
            'Expired',
            'Today',
            'Tomorrow',
            'This week',
            'Next 2 weeks',
            'This month',
        ]
        assert all(isinstance(b, ExpiryBucketDTO) for b in result)

    async def test_expired_items_counted(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Items past their expiry land in the 'Expired' bucket."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        await _make_item(
            db, org_id, loc_id, name='Old', expiry_date=date.today() - timedelta(days=5)
        )
        await db.commit()

        result = await core_api.queries.get_expiry_forecast_async(db, org_id)
        expired = next(b for b in result if b.period == 'Expired')
        assert expired.count == 1


@pytest.mark.asyncio
class TestCoreQueriesRecentActivity:
    """core_api.queries.get_recent_activity_async."""

    async def test_returns_history_entries(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
        async_test_user,
    ):
        """ItemHistory rows surface as ActivityDTOs."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        item = await _make_item(db, org_id, async_test_storage_location.id, name='Act')
        hist = ItemHistory(
            organization_id=org_id,
            item_id=item.id,
            action='CREATED',
            changes={'qty': 1},
            user_id=async_test_user.id,
        )
        db.add(hist)
        await db.commit()

        result = await core_api.queries.get_recent_activity_async(db, org_id)

        assert len(result) >= 1
        entry = next(r for r in result if r.id == hist.id)
        assert isinstance(entry, ActivityDTO)
        assert entry.action == 'CREATED'
        assert entry.item_name == 'Act'
        assert entry.user_name == async_test_user.full_name

    async def test_limit_caps_results(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """The limit parameter bounds the returned list size."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        result = await core_api.queries.get_recent_activity_async(db, org_id, limit=3)
        assert len(result) <= 3


@pytest.mark.asyncio
class TestCoreQueriesConsumption:
    """core_api.queries.get_consumption_stats_async."""

    async def test_empty_org_returns_zeros(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Org with no consumption history → all-zero stats."""
        db = real_async_db_session
        result = await core_api.queries.get_consumption_stats_async(
            db, async_test_storage_location.organization_id
        )
        assert isinstance(result, ConsumptionStatsDTO)
        assert result.most_consumed == []
        assert result.most_wasted == []
        assert result.waste_event_rate == 0.0

    async def test_consumed_items_aggregated(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Consumption ItemHistory rows aggregate into most_consumed."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        item = await _make_item(db, org_id, async_test_storage_location.id, name='Milk')
        await _record_outflow(db, item, action='USED', quantity=2, value=5.0)

        result = await core_api.queries.get_consumption_stats_async(db, org_id)

        assert result.total_consumed_value == 5.0
        assert len(result.most_consumed) == 1
        assert result.most_consumed[0].name == 'Milk'
        assert result.most_consumed[0].quantity == 2

    async def test_waste_event_rate_computed_from_discarded(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """waste_event_rate = discarded / (consumed + discarded)."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        item = await _make_item(
            db, org_id, async_test_storage_location.id, name='Bread'
        )
        # Consumed at no cost, thrown away at two: the waste rate counts
        # events, so it is answerable either way, and the value is not.
        await _record_outflow(db, item, action='USED', quantity=3, value=0.0)
        await _record_outflow(db, item, action='DISPOSED', quantity=1, value=2.0)

        result = await core_api.queries.get_consumption_stats_async(db, org_id)

        assert result.total_wasted_value == 2.0
        assert result.waste_event_rate == 0.5


@pytest.mark.asyncio
class TestCoreQueriesCostSummary:
    """core_api.queries.get_cost_summary_async."""

    async def test_empty_org_returns_zeros(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Org with no priced items → all-zero cost summary."""
        db = real_async_db_session
        result = await core_api.queries.get_cost_summary_async(
            db, async_test_storage_location.organization_id
        )
        assert isinstance(result, CostSummaryDTO)
        assert result.total_spent == 0.0
        assert result.waste_value_percentage == 0.0
        assert result.savings_opportunities == []
        assert len(result.monthly_trend) == 6

    async def test_total_spent_includes_priced_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """The period's receipts, priced by the ledger, feed total_spent."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        await _make_item(
            db,
            org_id,
            loc_id,
            name='Widget',
            quantity=Decimal('4'),
        )
        # An unpriced item and a priced one; the denominator reads the
        # valuation ledger's receipts, so the ledger gets the arrivals —
        # the unpriced one adds nothing, the priced one its 10 * 2 = 20.
        from datetime import UTC, datetime

        from app.models.item import Item as ItemModel
        from app.models.product_template import ProductTemplate
        from app.models.stock_valuation_layer import StockValuationLayer

        priced = ItemModel(
            organization_id=org_id,
            storage_location_id=loc_id,
            name='Gadget',
            quantity=Decimal('2'),
            purchase_price=Decimal('10'),
            currency='USD',
        )
        db.add(priced)
        template = ProductTemplate(name='Gadget', organization_id=org_id)
        db.add(template)
        await db.flush()
        db.add(
            StockValuationLayer(
                organization_id=org_id,
                product_template_id=template.id,
                quantity=Decimal('2'),
                remaining_qty=Decimal('2'),
                unit_cost=Decimal('10'),
                total_value=Decimal('20.00'),
                direction='IN',
                currency='USD',
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()

        result = await core_api.queries.get_cost_summary_async(db, org_id)

        # The priced receipt (10 * 2 = 20) counts; the unpriced one adds 0.
        assert result.total_spent == 20.0

    async def test_monthly_trend_has_six_buckets(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Always returns 6 monthly trend entries."""
        db = real_async_db_session
        result = await core_api.queries.get_cost_summary_async(
            db, async_test_storage_location.organization_id
        )
        assert len(result.monthly_trend) == 6


@pytest.mark.asyncio
class TestCoreQueriesRotationAnalysis:
    """core_api.queries.get_rotation_analysis_async."""

    async def test_empty_org_returns_zeros(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Org with no items → zero rotation metrics."""
        db = real_async_db_session
        result = await core_api.queries.get_rotation_analysis_async(
            db, async_test_storage_location.organization_id
        )
        assert isinstance(result, RotationAnalysisDTO)
        assert result.active_items_count == 0
        assert result.slow_movers == []
        assert result.dead_stock == []

    async def test_active_items_counted(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Items with added_date surface in active_items_count."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        await _make_item(db, org_id, async_test_storage_location.id, name='Recent')
        await db.commit()

        result = await core_api.queries.get_rotation_analysis_async(db, org_id)
        assert result.active_items_count == 1
        assert result.consumed_items_count == 0

    async def test_dead_stock_detected(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Items older than 90 days appear in dead_stock."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        from app.models.item import Item as ItemModel

        old_item = ItemModel(
            organization_id=org_id,
            storage_location_id=async_test_storage_location.id,
            name='Ancient',
            added_date=date.today() - timedelta(days=120),
        )
        db.add(old_item)
        await db.commit()

        result = await core_api.queries.get_rotation_analysis_async(db, org_id)
        assert result.dead_stock_count >= 1
        assert any(r.name == 'Ancient' for r in result.dead_stock)


@pytest.mark.asyncio
class TestCoreQueriesReconciliation:
    """core_api.queries.get_reconciliation_async."""

    async def test_empty_org_no_drift(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Org with no template-bound items → no drift, items_scanned 0."""
        db = real_async_db_session
        result = await core_api.queries.get_reconciliation_async(
            db, async_test_storage_location.organization_id
        )
        assert isinstance(result, ReconciliationDTO)
        assert result.items_scanned == 0
        assert result.quant_move_drift_count == 0
        assert result.layer_quant_drift_count == 0

    async def test_items_without_template_not_scanned(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Plain items (no template_id) are skipped — no card, no shelf to compare."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        await _make_item(db, org_id, async_test_storage_location.id, name='Plain')
        await db.commit()

        result = await core_api.queries.get_reconciliation_async(db, org_id)
        assert result.items_scanned == 0

    async def test_template_bound_items_are_scanned(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Template-bound items are scanned: they are what the shelf is summed from."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        tpl = await _make_template(db, org_id, name='Synced Tpl')
        await _make_item(
            db, org_id, loc_id, name='Synced', quantity=Decimal('3'), template_id=tpl.id
        )
        await db.commit()

        result = await core_api.queries.get_reconciliation_async(db, org_id)
        assert result.items_scanned >= 1


@pytest.mark.asyncio
class TestCoreQueriesExpenseForecast:
    """core_api.queries.get_expense_forecast_async."""

    async def test_empty_org_no_data(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Org with no purchase history → no_data trend, zero prediction."""
        db = real_async_db_session
        result = await core_api.queries.get_expense_forecast_async(
            db, async_test_storage_location.organization_id
        )
        assert isinstance(result, ExpenseForecastDTO)
        assert result.trend == 'no_data'
        assert result.predicted_spending == 0.0
        assert result.historical_avg == 0.0
        assert result.trend_percentage is None
        assert result.confidence == 0.0

    async def test_period_echoed(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """forecast_period echoes the requested period."""
        db = real_async_db_session
        result = await core_api.queries.get_expense_forecast_async(
            db, async_test_storage_location.organization_id, period='quarter'
        )
        assert result.forecast_period == 'quarter'

    async def test_top_cost_drivers_rank_what_was_actually_paid_for(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """A priced record reaches the ranking, and brings its total with it.

        What stood here asked the same empty organization as the two tests
        above it and then iterated ``result.top_cost_drivers``, a list the
        query had no rows to fill — so the loop body never ran once. What was
        left, ``assert isinstance(result.top_cost_drivers, list)``, is
        guaranteed by the DTO's own annotation; it would have passed just as
        happily against a service that returned nothing for an organization
        holding a hundred priced records.
        """
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id

        template = purchase_template(org_id, 'Rankable')
        db.add(template)
        await db.flush()
        db.add(
            Item(
                organization_id=org_id,
                storage_location_id=async_test_storage_location.id,
                name='Rankable',
                quantity=Decimal('3'),
                purchase_price=Decimal('7'),
            )
        )
        await db.commit()

        result = await core_api.queries.get_expense_forecast_async(db, org_id)

        assert len(result.top_cost_drivers) >= 1
        driver = result.top_cost_drivers[0]
        assert isinstance(driver, CategoryCostDTO)
        # Three at seven. The ranking multiplies by quantity on purpose —
        # without it one unit at 1000 and a thousand at 1 ranked the same.
        assert float(driver.total_spent) == pytest.approx(21.0)

    async def test_priced_items_drive_prediction(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Weeks of priced items produce a non-zero historical average.

        One item does not: a single week of purchases is not a rate, and the
        forecast now says so rather than multiplying that week by 4.33.
        """
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        from datetime import date, timedelta

        from app.models.item import Item as ItemModel

        template = purchase_template(org_id, 'Gadget')
        db.add(template)
        await db.flush()
        for week in range(8):
            on = date.today() - timedelta(days=7 * week)
            db.add(
                ItemModel(
                    organization_id=org_id,
                    storage_location_id=loc_id,
                    name=f'Gadget {week}',
                    quantity=Decimal('2'),
                    purchase_price=Decimal('10'),
                    currency='USD',
                    created_at=on,
                )
            )
            # Two at ten: the layer carries what the delivery cost in total.
            db.add(receipt_layer(org_id, template.id, value='20', on=on, quantity='2'))
        await db.commit()

        result = await core_api.queries.get_expense_forecast_async(db, org_id)
        assert result.historical_avg > 0.0
        assert result.weeks_of_data == 8
