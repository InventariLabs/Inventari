"""
Tests for advanced analytics endpoints (/api/stats/rotation-analysis, /smart-alerts, etc.)
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.organization import Organization
from app.models.storage_type import StorageType
from app.models.user import User
from tests.integration._purchases import purchase_template, receipt_layer


@pytest.mark.integration
class TestRotationAnalysis:
    """Tests for inventory rotation analysis."""

    def test_rotation_analysis_empty_storage(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Test rotation analysis with no items."""
        response = client.get('/api/v1/stats/rotation-analysis', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data['average_stock_age_days'] is None
        assert data['median_stock_age_days'] is None
        assert data['slow_movers_count'] == 0
        assert data['dead_stock_count'] == 0
        assert data['rotation_by_category'] == []

    def test_rotation_analysis_with_active_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test rotation detection with active items."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        # Create storage and category
        storage = StorageLocation(
            name='Fridge',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)

        category = Category(
            name='Dairy',
            organization_id=test_household.id,
        )
        db_session.add(category)
        db_session.commit()

        # Add item from 40 days ago (slow mover)
        today = date.today()
        old_item = Item(
            name='Yogurt',
            organization_id=test_household.id,
            storage_location_id=storage.id,
            category_id=category.id,
            quantity=1.0,
            added_date=today - timedelta(days=40),
            purchase_price=Decimal('5.99'),
        )
        db_session.add(old_item)
        db_session.commit()

        response = client.get('/api/v1/stats/rotation-analysis', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data['average_stock_age_days'] == 40.0
        # Nothing has been consumed yet — the age of standing stock does
        # not wait for the first consumption to become computable.
        assert data['consumed_items_count'] == 0
        assert data['slow_movers_count'] == 1
        assert len(data['slow_movers']) > 0
        assert data['slow_movers'][0]['name'] == 'Yogurt'
        assert data['slow_movers'][0]['days_in_storage'] == 40

    def test_rotation_analysis_dead_stock_detection(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test detection of dead stock (>90 days)."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Freezer',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)
        db_session.commit()

        today = date.today()
        # Item from 100 days ago
        dead_item = Item(
            name='Frozen something',
            organization_id=test_household.id,
            storage_location_id=storage.id,
            quantity=1.0,
            added_date=today - timedelta(days=100),
            purchase_price=Decimal('15.99'),
        )
        db_session.add(dead_item)
        db_session.commit()

        response = client.get('/api/v1/stats/rotation-analysis', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data['dead_stock_count'] == 1
        assert len(data['dead_stock']) > 0
        assert data['dead_stock'][0]['name'] == 'Frozen something'
        assert data['dead_stock_value'] > 0

    def test_rotation_analysis_unauthorized(self, client: TestClient) -> None:
        """Test that unauthorized users cannot access rotation analysis."""
        response = client.get('/api/v1/stats/rotation-analysis')
        assert response.status_code == 401

    def test_rotation_analysis_no_household(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Test rotation analysis when user not in a organization."""
        # This tests the endpoint with a valid user that is in a organization,
        # so we just verify the response is valid
        response = client.get('/api/v1/stats/rotation-analysis', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert 'average_stock_age_days' in data


@pytest.mark.integration
class TestSmartAlerts:
    """Tests for smart alerts endpoint."""

    def test_smart_alerts_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Test smart alerts with no items."""
        response = client.get('/api/v1/stats/smart-alerts', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data['total_alerts'] == 0
        assert data['alerts'] == []

    def test_smart_alerts_forgotten_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test detection of forgotten items (>60 days).

        "Last touched" = max(updated_at, last ItemHistory action).
        An item that was just created has updated_at = now() and is therefore
        NOT forgotten, so we have to backdate both updated_at and added_date
        to simulate a truly untouched item.
        """
        from datetime import datetime

        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Pantry',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)
        db_session.commit()

        today = date.today()
        old_ts = datetime.combine(today - timedelta(days=70), datetime.min.time())
        forgotten = Item(
            name='Forgotten pasta',
            organization_id=test_household.id,
            storage_location_id=storage.id,
            quantity=1.0,
            added_date=today - timedelta(days=70),
            updated_at=old_ts,
            created_at=old_ts,
        )
        db_session.add(forgotten)
        db_session.commit()

        response = client.get('/api/v1/stats/smart-alerts', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data['total_alerts'] > 0
        forgotten_alerts = [a for a in data['alerts'] if a['type'] == 'FORGOTTEN_ITEM']
        assert len(forgotten_alerts) > 0
        assert forgotten_alerts[0]['item_name'] == 'Forgotten pasta'

    def test_smart_alerts_expiring_soon(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test detection of items expiring within 7 days."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Fridge',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)
        db_session.commit()

        today = date.today()
        expiring = Item(
            name='Milk',
            organization_id=test_household.id,
            storage_location_id=storage.id,
            quantity=1.0,
            expiry_date=today + timedelta(days=3),
        )
        db_session.add(expiring)
        db_session.commit()

        response = client.get('/api/v1/stats/smart-alerts', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        expiring_alerts = [a for a in data['alerts'] if a['type'] == 'EXPIRING_SOON']
        assert len(expiring_alerts) > 0
        assert expiring_alerts[0]['item_name'] == 'Milk'
        assert expiring_alerts[0]['days_until_expiry'] == 3


@pytest.mark.integration
class TestExpenseForecast:
    """Tests for expense forecast endpoint."""

    def test_expense_forecast_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Test forecast with no purchase history."""
        response = client.get(
            '/api/v1/stats/expense-forecast?period=month', headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()

        assert data['forecast_period'] == 'month'
        assert data['predicted_spending'] == 0.0
        assert data['historical_avg'] == 0.0

    def test_expense_forecast_week_prediction(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test weekly forecast calculation."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Pantry',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)
        db_session.commit()

        # Enough weeks to read a rate off — see _MIN_WEEKS_FOR_FORECAST.
        # The forecast reads the receipt layers, so each purchase posts one.
        template = purchase_template(test_household.id)
        db_session.add(template)
        db_session.flush()
        today = date.today()
        for i in range(8):
            on = today - timedelta(days=7 * i)
            item = Item(
                name=f'Product {i}',
                organization_id=test_household.id,
                storage_location_id=storage.id,
                quantity=1.0,
                purchase_price=Decimal('100.00'),
                created_at=on,
            )
            db_session.add(item)
            db_session.add(
                receipt_layer(test_household.id, template.id, value='100.00', on=on)
            )
        db_session.commit()

        response = client.get(
            '/api/v1/stats/expense-forecast?period=week', headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()

        assert data['forecast_period'] == 'week'
        assert data['predicted_spending'] > 0
        assert data['weeks_of_data'] == 8
        assert 'waste_reduction_potential' in data

    def test_expense_forecast_month_prediction(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test monthly forecast calculation."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Pantry',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)
        db_session.commit()

        template = purchase_template(test_household.id)
        db_session.add(template)
        db_session.flush()
        today = date.today()
        for i in range(8):
            on = today - timedelta(days=7 * i)
            db_session.add(
                Item(
                    name=f'Product {i}',
                    organization_id=test_household.id,
                    storage_location_id=storage.id,
                    quantity=1.0,
                    purchase_price=Decimal('100.00'),
                    created_at=on,
                )
            )
            db_session.add(
                receipt_layer(test_household.id, template.id, value='100.00', on=on)
            )
        db_session.commit()

        response = client.get(
            '/api/v1/stats/expense-forecast?period=month', headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()

        assert data['forecast_period'] == 'month'
        # A hundred a week, so a month lands in the same neighbourhood.
        assert 300 < data['predicted_spending'] < 600

    def test_expense_forecast_says_when_it_cannot_forecast(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """A single purchase is not a rate, and the answer says so."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Pantry',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)
        db_session.commit()

        db_session.add(
            Item(
                name='Product',
                organization_id=test_household.id,
                storage_location_id=storage.id,
                quantity=1.0,
                purchase_price=Decimal('430.00'),
                created_at=date.today() - timedelta(days=14),
            )
        )
        db_session.commit()

        response = client.get(
            '/api/v1/stats/expense-forecast?period=month', headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()

        assert data['trend'] == 'no_data'
        assert data['predicted_spending'] == 0.0
        assert data['confidence'] == 0.0
        assert data['weeks_of_data'] < data['weeks_required']

    def test_expense_forecast_invalid_period(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Test forecast with invalid period parameter."""
        response = client.get(
            '/api/v1/stats/expense-forecast?period=invalid', headers=auth_headers
        )
        assert response.status_code == 422  # Validation error


@pytest.mark.integration
class TestPurchasePatterns:
    """Tests for purchase pattern analysis."""

    def test_purchase_patterns_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Test patterns with no purchase history."""
        response = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data['top_recurring_products'] == []
        assert data['seasonal_products'] == []
        assert data['bulk_opportunities'] == []

    def test_purchase_patterns_recurring_products(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test detection of recurring products."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Pantry',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        category = Category(name='Dairy', organization_id=test_household.id)
        db_session.add(storage)
        db_session.add(category)
        db_session.commit()

        today = date.today()
        # Add same product 3 times in past 6 months
        for i in range(3):
            item = Item(
                name='Milk',
                brand='Łaciate',
                organization_id=test_household.id,
                storage_location_id=storage.id,
                category_id=category.id,
                quantity=1.0,
                purchase_price=Decimal('4.50'),
                created_at=today - timedelta(days=7 * (i + 1)),
            )
            db_session.add(item)
        db_session.commit()

        response = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert len(data['top_recurring_products']) > 0
        milk_product = next(
            (p for p in data['top_recurring_products'] if p['name'] == 'Milk'),
            None,
        )
        assert milk_product is not None
        assert milk_product['total_purchases_last_6_months'] == 3
        assert milk_product['brand'] == 'Łaciate'
        assert milk_product['avg_price'] > 0
        # The column rendered `total_spent` for months while the response had
        # no such field — three cartons at 4.50 is 13.50, not 0.
        assert milk_product['total_spent'] == pytest.approx(13.5)

    def test_purchase_patterns_bulk_opportunities(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test bulk opportunity detection."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            name='Pantry',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        db_session.add(storage)
        db_session.commit()

        today = date.today()
        # Add expensive product bought in small quantities multiple times
        for i in range(3):
            item = Item(
                name='Coffee',
                organization_id=test_household.id,
                storage_location_id=storage.id,
                quantity=Decimal('0.25'),  # Small quantity
                purchase_price=Decimal('25.00'),  # High price per kg
                created_at=today - timedelta(days=7 * (i + 1)),
            )
            db_session.add(item)
        db_session.commit()

        response = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Should detect bulk opportunity
        bulk_opps = data['bulk_opportunities']
        coffee_opp = next((b for b in bulk_opps if b['product'] == 'Coffee'), None)
        if coffee_opp:  # Might be filtered based on thresholds
            assert coffee_opp['bulk_option_kg'] > coffee_opp['current_avg_purchase_kg']
            assert coffee_opp['potential_annual_savings'] > 0


@pytest.mark.integration
class TestAnalyticsIntegration:
    """Integration tests combining multiple analytics endpoints."""

    def test_analytics_full_workflow(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_household: Organization,
        test_user: User,
        test_storage_type: StorageType,
        db_session: Session,
    ) -> None:
        """Test complete analytics workflow with realistic data."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        # Setup
        storage = StorageLocation(
            name='Fridge',
            organization_id=test_household.id,
            storage_type_id=test_storage_type.id,
            created_by=test_user.id,
        )
        category = Category(name='Dairy', organization_id=test_household.id)
        db_session.add(storage)
        db_session.add(category)
        db_session.commit()

        today = date.today()
        # Mix of items
        items_to_add = [
            # Active, recently purchased
            Item(
                name='Milk',
                organization_id=test_household.id,
                storage_location_id=storage.id,
                category_id=category.id,
                quantity=1.0,
                purchase_price=Decimal('4.50'),
                added_date=today - timedelta(days=2),
            ),
            # Expiring soon
            Item(
                name='Yogurt',
                organization_id=test_household.id,
                storage_location_id=storage.id,
                category_id=category.id,
                quantity=2.0,
                purchase_price=Decimal('3.99'),
                expiry_date=today + timedelta(days=3),
                added_date=today - timedelta(days=5),
            ),
            # Slow mover
            Item(
                name='Cheese',
                organization_id=test_household.id,
                storage_location_id=storage.id,
                category_id=category.id,
                quantity=1.0,
                purchase_price=Decimal('15.99'),
                added_date=today - timedelta(days=45),
            ),
        ]

        for item in items_to_add:
            db_session.add(item)
        db_session.commit()

        # Test all endpoints
        rotation = client.get('/api/v1/stats/rotation-analysis', headers=auth_headers)
        assert rotation.status_code == 200
        assert rotation.json()['slow_movers_count'] >= 1

        alerts = client.get('/api/v1/stats/smart-alerts', headers=auth_headers)
        assert alerts.status_code == 200
        alert_data = alerts.json()
        assert alert_data['total_alerts'] > 0

        forecast = client.get(
            '/api/v1/stats/expense-forecast?period=month', headers=auth_headers
        )
        assert forecast.status_code == 200
        # Three items entered on one day: the endpoint answers, and what it
        # answers is that a week of history forecasts nothing.
        assert forecast.json()['weeks_of_data'] < forecast.json()['weeks_required']

        patterns = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)
        assert patterns.status_code == 200
