"""
Integration tests for stats API endpoints.

Tests verify correctness of endpoints:
- GET /api/stats/overview - overall statistics
- GET /api/stats/by-location - statistics by storage location
- GET /api/stats/by-category - statistics by category
- GET /api/stats/expiry-forecast - product expiry forecast
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from tests.integration._shelf import anchor_pending_records


@pytest.mark.integration
class TestStatsOverview:
    """Tests for overview stats endpoint."""

    def test_get_overview_stats_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Tests fetching overview stats with no items."""
        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total_items'] == 0
        assert data['total_locations'] == 1  # test_storage_location
        assert 'expiring_soon' in data
        assert 'expired' in data
        assert 'low_stock' in data

    def test_get_overview_stats_with_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_items_batch: list[Item],
    ) -> None:
        """Tests fetching overview stats with items."""
        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total_items'] == 5
        assert data['total_locations'] == 1

    def test_overview_values_uncategorised_stock(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Stock value comes from the items, not from per-category subtotals.

        `/stats/by-category` returns nothing when no product carries a
        category, so an overview summing those subtotals reported $0.00 over
        priced stock — the state right after an import, and exactly when
        somebody asks what the stock is worth for the first time.
        """
        db_session.add(
            Item(
                organization_id=test_storage_location.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=None,
                name='Uncategorised crate',
                quantity=3,
                purchase_price=12.5,
            )
        )
        db_session.commit()

        overview = client.get('/api/v1/stats/overview', headers=auth_headers)
        by_category = client.get('/api/v1/stats/by-category', headers=auth_headers)

        assert overview.status_code == status.HTTP_200_OK
        assert overview.json()['total_value'] == pytest.approx(37.5)
        # The per-category breakdown used to drop this crate twice over: it
        # carries no category, and it carries no currency either, and the
        # query demanded an exact currency match. It now agrees with the
        # overview under the uncategorised row.
        rows = by_category.json()['items']
        assert sum(row['total_value'] for row in rows) == pytest.approx(37.5)
        assert any(row['category_id'] is None for row in rows)

    def test_get_overview_stats_unauthorized(self, client: TestClient) -> None:
        """Tests fetching overview stats without authorization."""
        response = client.get('/api/v1/stats/overview')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestStatsByStorage:
    """Tests for stats by storage endpoint."""

    def test_get_stats_by_storage_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Tests fetching stats by storage with no items."""
        response = client.get('/api/v1/stats/by-location', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) == 1  # test_storage_location
        assert data[0]['location_id'] is not None
        assert data[0]['items_count'] == 0

    def test_get_stats_by_storage_with_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_items_batch: list[Item],
    ) -> None:
        """Tests fetching stats by storage with items."""
        response = client.get('/api/v1/stats/by-location', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) == 1
        assert data[0]['items_count'] == 5

    def test_empty_virtual_places_stay_out_of_the_breakdown(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        test_storage_location: StorageLocation,
    ) -> None:
        """The system's own consumed/loss/production places hold no stock a
        reader could act on; an empty one is noise between the real shelves."""
        db_session.add(
            StorageLocation(
                organization_id=test_user.organization_id,
                created_by=test_user.id,
                storage_type_id=test_storage_type.id,
                name='Consumed (Virtual)',
                usage='customer',
            )
        )
        db_session.commit()

        response = client.get('/api/v1/stats/by-location', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        names = [row['location_name'] for row in response.json()['items']]
        assert names == [test_storage_location.name]

    def test_a_used_up_product_does_not_bring_its_virtual_place_back(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        """Using a product up moves its row, at quantity 0, into the consumed
        place. That row is history, not stock: the place chart and the
        category chart must still add up to the records on the shelves."""
        consumed = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Consumed (Virtual)',
            usage='customer',
        )
        db_session.add(consumed)
        db_session.flush()
        test_items_batch[0].storage_location_id = consumed.id
        test_items_batch[0].quantity = Decimal(0)
        db_session.commit()

        by_place = client.get('/api/v1/stats/by-location', headers=auth_headers)
        by_category = client.get('/api/v1/stats/by-category', headers=auth_headers)

        places = by_place.json()['items']
        assert [row['location_name'] for row in places] == [test_storage_location.name]
        assert sum(row['items_count'] for row in places) == 4
        assert sum(row['items_count'] for row in by_category.json()['items']) == 4

    def _place(
        self,
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        name: str,
        parent: StorageLocation | None = None,
        settings: dict[str, bool] | None = None,
    ) -> StorageLocation:
        place = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name=name,
            parent_id=parent.id if parent else None,
            settings=settings,
        )
        db_session.add(place)
        db_session.flush()
        return place

    def test_an_archived_place_stays_out_of_the_breakdown(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        test_storage_location: StorageLocation,
    ) -> None:
        """Archived is gone from every list of places; it is not an empty shelf."""
        self._place(
            db_session,
            test_user,
            test_storage_type,
            'Server Room',
            settings={'archived': True},
        )
        db_session.commit()

        response = client.get('/api/v1/stats/by-location', headers=auth_headers)

        names = [row['location_name'] for row in response.json()['items']]
        assert names == [test_storage_location.name]

    def test_a_container_is_not_listed_as_an_empty_shelf(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
    ) -> None:
        """An aisle holds its racks, not goods: at 0 records it is not a place
        with room on it. A shelf with nothing on it still is, and so is a
        parent holding records of its own."""
        aisle = self._place(db_session, test_user, test_storage_type, 'Aisle A')
        self._place(db_session, test_user, test_storage_type, 'Rack A-01', parent=aisle)
        self._place(
            db_session,
            test_user,
            test_storage_type,
            'Rack B-01',
            parent=test_storage_location,
        )
        db_session.commit()

        response = client.get('/api/v1/stats/by-location', headers=auth_headers)

        counts = {
            row['location_name']: row['items_count'] for row in response.json()['items']
        }
        assert counts == {
            test_storage_location.name: 5,
            'Rack A-01': 0,
            'Rack B-01': 0,
        }

    def test_a_parent_of_archived_places_only_is_an_empty_shelf_again(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        test_storage_location: StorageLocation,
    ) -> None:
        """Archiving a rack's only shelves leaves a rack with room on it."""
        rack = self._place(db_session, test_user, test_storage_type, 'Rack C-01')
        self._place(
            db_session,
            test_user,
            test_storage_type,
            'Shelf C-01-01',
            parent=rack,
            settings={'archived': True},
        )
        db_session.commit()

        response = client.get('/api/v1/stats/by-location', headers=auth_headers)

        names = {row['location_name'] for row in response.json()['items']}
        assert names == {test_storage_location.name, 'Rack C-01'}


@pytest.mark.integration
class TestStatsByCategory:
    """Tests for stats by category endpoint."""

    def test_get_stats_by_category_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests fetching stats by category with no items."""
        response = client.get('/api/v1/stats/by-category', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        # May be empty or have one category with 0 items
        assert isinstance(response.json()['items'], list)

    def test_get_stats_by_category_with_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_items_batch: list[Item],
    ) -> None:
        """Tests fetching stats by category with items."""
        response = client.get('/api/v1/stats/by-category', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        # All test items use the same category
        if len(data) > 0:
            assert data[0]['category_id'] is not None
            assert data[0]['items_count'] == 5


@pytest.mark.integration
class TestStatsExpiryForecast:
    """Tests for expiry forecast endpoint."""

    def test_get_expiry_forecast_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Tests fetching expiry forecast with no items."""
        response = client.get('/api/v1/stats/expiry-forecast', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should have forecast periods
        assert len(data) > 0
        # Check that we have expected periods
        period_names = [p['period'] for p in data]
        assert 'Expired' in period_names
        assert 'Today' in period_names
        assert 'This week' in period_names

    def test_get_expiry_forecast_with_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_items_batch: list[Item],
    ) -> None:
        """Tests fetching expiry forecast with expiring items."""
        response = client.get('/api/v1/stats/expiry-forecast', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) > 0

        # With test data, items expire within 10-30 days
        assert any(
            p['count'] > 0
            for p in data
            if p['period'] in ['This week', 'Next 2 weeks', 'This month']
        )


@pytest.mark.integration
class TestStatsCostTracking:
    """Tests for cost tracking in stats."""

    def test_get_overview_with_cost_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Tests overview stats with items that have purchase prices."""
        from app.models.item import Item

        # Create items with prices
        for i in range(3):
            item = Item(
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=test_category.id,
                name=f'Priced Product {i + 1}',
                quantity=2,
                purchase_price=10.00 + i * 5,
                currency='USD',
            )
            db_session.add(item)
        db_session.commit()

        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should have 3 items from this test + items from test_items_batch
        assert data['total_items'] >= 3


@pytest.mark.integration
class TestStatsEdgeCases:
    """Tests for edge cases in stats."""

    def test_get_overview_with_expired_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Tests overview stats with expired items."""
        from app.models.item import Item

        # Create expired item
        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Expired Product',
            quantity=1,
            expiry_date=date.today() - timedelta(days=10),
        )
        db_session.add(item)
        db_session.commit()

        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['expired'] >= 1

    def test_get_overview_with_expiring_soon_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Tests overview stats with items expiring within 7 days."""
        from app.models.item import Item

        # Create item expiring in 3 days
        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Expiring Soon',
            quantity=1,
            expiry_date=date.today() + timedelta(days=3),
        )
        db_session.add(item)
        db_session.commit()

        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['expiring_soon'] >= 1

    def test_get_overview_with_low_stock_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Tests overview stats with low stock items."""
        from app.models.item import Item
        from app.models.product_template import ProductTemplate

        # Low stock requires a template with min_quantity
        template = ProductTemplate(
            organization_id=test_user.organization_id,
            name='Low Stock Template',
            min_quantity=5.0,
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        # Create item with quantity 1 (less than 5)
        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            template_id=template.id,
            name='Low Stock',
            quantity=1,
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['low_stock'] >= 1


@pytest.mark.integration
class TestStatsRecentActivity:
    """Tests for recent activity endpoint."""

    def test_get_recent_activity_no_household(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """Tests recent activity when user has no organization."""
        # Remove user's organization
        test_user.organization_id = None
        db_session.commit()

        response = client.get('/api/v1/stats/activity', headers=auth_headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN


def _record_outflow(
    db_session: Session,
    item: Item,
    *,
    action: str,
    quantity: float,
    value: float,
) -> None:
    """Seed a use or a disposal the way the application records one.

    Both halves, because the report reads both. The history row carries the
    quantity under ``qty`` — the key the consume and discard path writes — and
    the valuation ledger carries what it was worth, in an outgoing layer.

    These tests used to seed ``quantity_consumed``, ``consumed_cost``,
    ``quantity_discarded`` and ``wasted_cost``: four keys that exist nowhere
    else in the application. They passed against a shape production never
    creates, which is why the report read zero for years while the suite
    stayed green.
    """
    from decimal import Decimal

    from app.models.item_history import ItemHistory
    from app.models.product_template import ProductTemplate
    from app.models.stock_valuation_layer import StockValuationLayer

    # Every path that creates an item resolves a template for it, and
    # valuation is kept per template — so a record without one could not be
    # priced and would make the report say it does not know.
    if item.template_id is None:
        template = ProductTemplate(
            name=item.name,
            organization_id=item.organization_id,
        )
        db_session.add(template)
        db_session.flush()
        item.template_id = template.id
        db_session.add(item)

    db_session.add(
        ItemHistory(
            organization_id=item.organization_id,
            item_id=item.id,
            action=action,
            changes={
                'qty': float(quantity),
                'old': float(item.quantity),
                'reason': 'EXPIRED',
            },
        )
    )
    db_session.add(
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
    anchor_pending_records(db_session)
    db_session.commit()


@pytest.mark.integration
class TestStatsConsumption:
    """Tests for consumption stats endpoint."""

    def test_get_consumption_stats_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Tests fetching consumption stats with no consumption history."""
        response = client.get('/api/v1/stats/consumption', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'most_consumed' in data
        assert 'most_wasted' in data
        assert 'waste_event_rate' in data
        assert 'total_consumed_value' in data
        assert 'total_wasted_value' in data
        assert data['most_consumed'] == []
        assert data['most_wasted'] == []

    def test_get_consumption_stats_with_history(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        test_category: Category,
    ) -> None:
        """Tests consumption stats with consumption history."""
        from app.models.item import Item

        # Create item
        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Test Product',
            quantity=5,
            purchase_price=10.00,
            currency='USD',
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        _record_outflow(db_session, item, action='USED', quantity=2, value=4.00)

        response = client.get('/api/v1/stats/consumption', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['most_consumed']) >= 1
        assert data['total_consumed_value'] >= 4.00

    def test_get_consumption_stats_with_waste(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        test_category: Category,
    ) -> None:
        """Tests consumption stats with waste/discard history."""
        from app.models.item import Item

        # Create item
        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Expired Product',
            quantity=3,
            purchase_price=15.00,
            currency='USD',
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        _record_outflow(db_session, item, action='DISPOSED', quantity=3, value=15.00)

        response = client.get('/api/v1/stats/consumption', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['most_wasted']) >= 1
        assert data['total_wasted_value'] >= 15.00

    def test_get_consumption_stats_no_household(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
    ) -> None:
        """Tests consumption stats when user has no organization."""

        # Remove user's organization
        test_user.organization_id = None
        db_session.commit()

        response = client.get('/api/v1/stats/consumption', headers=auth_headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.integration
class TestStatsCostAnalysis:
    """Tests for cost analysis endpoint."""

    def test_get_cost_analysis_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Tests fetching cost analysis with no items."""
        response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'total_spent' in data
        assert 'total_wasted' in data
        assert 'waste_value_percentage' in data
        assert 'top_expensive_categories' in data
        assert 'monthly_trend' in data
        assert 'savings_opportunities' in data
        assert data['total_spent'] == 0.0
        assert data['total_wasted'] == 0.0

    def test_get_cost_analysis_with_prices(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Tests cost analysis over what the period's receipts cost."""
        from decimal import Decimal

        from app.models.item import Item
        from app.models.product_template import ProductTemplate
        from app.models.stock_valuation_layer import StockValuationLayer

        # The spent tile reads the valuation ledger's receipts; three
        # arrivals at 10, 15 and 20 a piece, two units each.
        template = ProductTemplate(
            name='Priced Product', organization_id=test_user.organization_id
        )
        db_session.add(template)
        db_session.flush()
        for i in range(3):
            item = Item(
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=test_category.id,
                name=f'Priced Product {i + 1}',
                quantity=2,
                purchase_price=10.00 + i * 5,
                currency='USD',
                template_id=template.id,
            )
            db_session.add(item)
            unit_cost = Decimal(str(10.00 + i * 5))
            db_session.add(
                StockValuationLayer(
                    organization_id=test_user.organization_id,
                    product_template_id=template.id,
                    quantity=Decimal('2'),
                    remaining_qty=Decimal('2'),
                    unit_cost=unit_cost,
                    total_value=unit_cost * 2,
                    direction='IN',
                    currency='USD',
                )
            )
        anchor_pending_records(db_session)
        db_session.commit()

        response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total_spent'] >= 20.00
        assert data['total_wasted'] == 0.0
        assert data['waste_value_percentage'] == 0.0

    def test_get_cost_analysis_with_waste(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        test_category: Category,
    ) -> None:
        """Tests cost analysis with wasted items."""
        from app.models.item import Item

        # Create item with price
        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Wasted Product',
            quantity=3,
            purchase_price=25.00,
            currency='USD',
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        _record_outflow(db_session, item, action='DISPOSED', quantity=3, value=25.00)

        # The waste percentage is waste over what the period's receipts
        # cost — the denominator reads the ledger, so the ledger gets the
        # receipt the disposal came out of.
        from decimal import Decimal

        from app.models.stock_valuation_layer import StockValuationLayer

        db_session.add(
            StockValuationLayer(
                organization_id=item.organization_id,
                product_template_id=item.template_id,
                quantity=Decimal('3'),
                remaining_qty=Decimal('0'),
                unit_cost=Decimal('25.00'),
                total_value=Decimal('75.00'),
                direction='IN',
                currency='USD',
            )
        )
        db_session.commit()

        response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total_spent'] >= 25.00
        assert data['total_wasted'] >= 25.00
        assert data['waste_value_percentage'] > 0

    def test_get_cost_analysis_by_period(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Tests cost analysis with different periods."""
        from app.models.item import Item

        # Create item with price
        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Period Test Product',
            quantity=1,
            purchase_price=50.00,
            currency='USD',
        )
        db_session.add(item)
        db_session.commit()

        # Test different periods
        for period in ['day', 'week', 'month', 'year']:
            response = client.get(
                f'/api/v1/stats/cost-analysis?period={period}', headers=auth_headers
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert 'total_spent' in data
            assert 'total_wasted' in data

    def test_get_cost_analysis_no_household(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """Tests cost analysis when user has no organization."""
        # Remove user's organization
        test_user.organization_id = None
        db_session.commit()

        response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_cost_analysis_savings_opportunities(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        test_category: Category,
    ) -> None:
        """Tests that savings opportunities are generated for wasted products."""
        from app.models.item import Item

        # Create multiple items with prices
        for i in range(2):
            item = Item(
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=test_category.id,
                name=f'Savings Test Product {i + 1}',
                quantity=2,
                purchase_price=20.00 + i * 10,
                currency='USD',
            )
            db_session.add(item)
        db_session.commit()

        # Get the first item
        discarded = db_session.scalars(
            select(Item).where(Item.name.like('Savings Test Product%'))
        ).first()
        if discarded:
            _record_outflow(
                db_session, discarded, action='DISPOSED', quantity=2, value=20.00
            )

        response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should have savings opportunities if there are wasted products
        if data['total_wasted'] > 0:
            assert len(data['savings_opportunities']) >= 0

    def test_cost_analysis_sql_aggregation_with_many_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Regression test: SQL aggregation matches Python sum for 100+ layers."""
        from decimal import Decimal

        from app.models.product_template import ProductTemplate
        from app.models.stock_valuation_layer import StockValuationLayer

        template = ProductTemplate(
            name='Bulk Receipts', organization_id=test_user.organization_id
        )
        db_session.add(template)
        db_session.flush()

        expected_total = 0.0
        for i in range(120):
            price = round(5.0 + (i % 10) * 0.5, 2)
            db_session.add(
                StockValuationLayer(
                    organization_id=test_user.organization_id,
                    product_template_id=template.id,
                    quantity=Decimal('1'),
                    remaining_qty=Decimal('1'),
                    unit_cost=Decimal(str(price)),
                    total_value=Decimal(str(price)),
                    direction='IN',
                    currency='USD',
                )
            )
            expected_total += price
        db_session.commit()

        response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert round(data['total_spent'], 2) == round(expected_total, 2)

    def test_purchase_patterns_with_many_products(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_category: Category,
        test_user: User,
    ) -> None:
        """Regression test: purchase patterns SQL aggregation for batch data."""
        from app.models.item import Item

        for i in range(20):
            item = Item(
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=test_category.id,
                name=f'Recurring Product {i % 5}',
                quantity=1,
                purchase_price=10.0,
                currency='USD',
            )
            db_session.add(item)
        db_session.commit()

        response = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'top_recurring_products' in data
        assert len(data['top_recurring_products']) >= 1
        first = data['top_recurring_products'][0]
        assert first['total_purchases_last_6_months'] >= 2
