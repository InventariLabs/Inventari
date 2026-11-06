"""Integration tests for valuation API endpoints.

Covers:
- GET /equipment/valuation — fleet valuation
- GET /equipment/{item_id}/valuation — single asset valuation
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation


def _make_item_with_price(
    db_session: Session,
    org: Organization,
    storage_location: StorageLocation,
    category: Category,
    *,
    name: str,
    price: float | None = None,
    purchase_date: str | None = None,
    status: str = 'AVAILABLE',
    serial: str | None = None,
    useful_life_years: int | None = None,
) -> Item:
    from app.models.item import Item

    meta: dict[str, dict[str, Any]] = {'equipment': {'equipment_status': status}}
    if purchase_date:
        meta['equipment']['purchase_date'] = purchase_date
    if serial:
        meta['equipment']['serial_number'] = serial
    if useful_life_years is not None:
        meta['equipment']['useful_life_years'] = useful_life_years

    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=storage_location.id,
        category_id=category.id,
        quantity=1,
        purchase_price=Decimal(str(price)) if price is not None else None,
        meta_data=meta,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestAssetValuationEndpoint:
    """Tests for GET /equipment/{item_id}/valuation."""

    def test_valuation_returns_correct_fields(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        eq_item.purchase_price = Decimal('1200.00')
        meta = dict(eq_item.meta_data or {})
        meta['equipment'] = {
            **meta.get('equipment', {}),
            'purchase_date': '2024-01-01',
            'serial_number': 'SN-VAL-001',
        }
        eq_item.meta_data = meta
        flag_modified(eq_item, 'meta_data')
        db_session.commit()

        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['item_id'] == str(eq_item.id)
        assert data['item_name'] == eq_item.name
        assert data['serial_number'] == 'SN-VAL-001'
        assert float(data['purchase_price']) == 1200.00
        assert float(data['book_value']) >= 0
        assert data['is_depreciable'] is True
        assert data['useful_life_years'] == 5

    def test_valuation_item_without_price_is_not_depreciable(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_depreciable'] is False

    def test_valuation_nonexistent_item_returns_404(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            '/api/v1/equipment/00000000-0000-0000-0000-000000000000/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_valuation_requires_auth(self, client: TestClient, eq_item: Item) -> None:
        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/valuation',
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_valuation_fully_depreciated(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        eq_item.purchase_price = Decimal('500.00')
        meta = dict(eq_item.meta_data or {})
        meta['equipment'] = {
            **meta.get('equipment', {}),
            'purchase_date': '2015-01-01',
        }
        eq_item.meta_data = meta
        flag_modified(eq_item, 'meta_data')
        db_session.commit()

        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['book_value']) == 0
        assert float(data['depreciation_pct']) == 100.0

    def test_valuation_zero_useful_life_is_not_depreciable(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A zero-year life is a missing configuration, not a fact.

        The asset used to come back fully depreciated on its purchase date:
        book value 0.00 and 100% depreciation, inferred from a number nobody
        entered. It now reads as not depreciable at all.
        """
        eq_item.purchase_price = Decimal('1000.00')
        meta = dict(eq_item.meta_data or {})
        meta['equipment'] = {
            **meta.get('equipment', {}),
            'purchase_date': '2015-01-01',
            'useful_life_years': 0,
        }
        eq_item.meta_data = meta
        flag_modified(eq_item, 'meta_data')
        db_session.commit()

        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_depreciable'] is False
        assert float(data['depreciation_pct']) == 0
        assert float(data['book_value']) == 1000


@pytest.mark.integration
class TestFleetValuationEndpoint:
    """Tests for GET /equipment/valuation."""

    def test_fleet_valuation_empty_org(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 0
        assert float(data['total_book_value']) == 0
        assert data['by_category'] == []
        assert data['asset_count'] == 0

    def test_fleet_valuation_with_assets(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Laptop A',
            price=1200,
            purchase_date='2023-01-01',
            serial='SN-A',
        )
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Laptop B',
            price=800,
            purchase_date='2024-06-01',
            serial='SN-B',
        )

        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 2000
        assert float(data['total_book_value']) > 0
        assert data['asset_count'] == 2
        assert len(data['by_category']) == 1
        assert data['by_category'][0]['category_name'] == 'Laptop'
        assert data['by_category'][0]['asset_count'] == 2

    def test_fleet_valuation_excludes_foreign_currency_assets(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        """The sum must not add amounts in different
        currencies; foreign-currency assets are reported as excluded."""
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Local USD',
            price=1000,
        )
        foreign = _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Foreign EUR',
            price=500,
        )
        foreign.currency = 'EUR'
        db_session.add(foreign)
        db_session.commit()

        response = client.get('/api/v1/equipment/valuation', headers=eq_auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 1000
        assert data['asset_count'] == 1
        assert data['excluded_count'] == 1

    def test_fleet_valuation_covers_the_asset_under_no_category(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The valuation reads the fleet the module's own list reads.

        A priced asset filed under no category stood in the register while
        the fleet valuation summed past it — the fleet value sat lower than
        the register the same screen links to.
        """
        item = Item(
            name='Rack 42U Open Frame',
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=None,
            module_name='equipment',
            quantity=1,
            purchase_price=Decimal('900'),
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(item)
        db_session.commit()

        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['asset_count'] == 1
        assert float(data['total_purchase_value']) == 900

    def test_fleet_valuation_reports_unpriced_assets_as_excluded(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        """An asset received without an invoice sits in the
        register but cannot be summed. It used to fall out of the loop
        without a trace while ``excluded_count`` claimed nothing was
        skipped — the number the totals rest on was quietly too low."""
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Laptop A',
            price=1200,
        )
        donated = _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Donated monitor',
            price=None,
        )
        assert donated.purchase_price is None

        response = client.get('/api/v1/equipment/valuation', headers=eq_auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 1200
        assert data['asset_count'] == 1
        assert data['excluded_count'] == 1

    def test_asset_valuation_inherits_category_useful_life(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """An asset without ``useful_life_years`` in its
        meta inherits the default declared by its category."""
        eq_item.meta_data = {'equipment': {'equipment_status': 'AVAILABLE'}}
        eq_item.purchase_price = Decimal('1000')
        assert eq_item.category is not None
        eq_item.category.field_definitions = [
            {
                'key': 'useful_life_years',
                'type': 'number',
                'label': 'Useful Life (years)',
                'visible': True,
                'required': False,
                'default': 10,
            }
        ]
        flag_modified(eq_item, 'meta_data')
        db_session.add(eq_item)
        db_session.commit()

        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/valuation',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['useful_life_years'] == 10

    def test_fleet_valuation_excludes_retired(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Active Laptop',
            price=1000,
            purchase_date='2024-01-01',
        )
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Retired Laptop',
            price=500,
            status='RETIRED',
        )

        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 1000
        assert data['asset_count'] == 1

    @pytest.mark.parametrize('role', ['user', 'viewer'])
    def test_fleet_valuation_is_refused_to_an_ordinary_member(
        self, client: TestClient, h: ModuleTestHelper, eq_org: Organization, role: str
    ) -> None:
        """The totals are the organization's finances; the overview shows
        them to administrators and managers only, and the API says the same."""
        member = h.create_user(eq_org, email=f'{role}_val@test.com', role=role)

        response = client.get(
            '/api/v1/equipment/valuation', headers=h.get_auth_headers(member)
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_fleet_valuation_is_open_to_a_manager(
        self, client: TestClient, h: ModuleTestHelper, eq_org: Organization
    ) -> None:
        manager = h.create_user(eq_org, email='manager_val@test.com', role='manager')

        response = client.get(
            '/api/v1/equipment/valuation', headers=h.get_auth_headers(manager)
        )

        assert response.status_code == status.HTTP_200_OK

    def test_fleet_valuation_requires_auth(self, client: TestClient) -> None:
        response = client.get('/api/v1/equipment/valuation')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_fleet_valuation_depreciation_sums(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Old Laptop',
            price=1000,
            purchase_date='2021-01-01',
        )

        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        total_dep = float(data['total_depreciation'])
        total_purch = float(data['total_purchase_value'])
        total_book = float(data['total_book_value'])
        assert abs((total_purch - total_book) - total_dep) < 0.02

    def test_fleet_valuation_items_without_price_excluded(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Priced Item',
            price=500,
        )
        from app.models.item import Item

        free_item = Item(
            name='Free Item',
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=eq_category.id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(free_item)
        db_session.commit()

        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 500
        assert data['asset_count'] == 1
        assert len(data['by_category']) == 1
        assert data['by_category'][0]['asset_count'] == 1

    def test_fleet_valuation_lends_book_value_only_to_configured_assets(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        """Depreciation is conditional: a purchase price alone is not a
        configuration.

        An undated asset has no computed book value, so it is counted at
        purchase value — the figure that is known — while the book and
        depreciation totals cover only the asset carrying a purchase date
        and a useful life. The dated asset (2015 on the 5-year default) is
        fully depreciated on any test day, so it contributes exactly 1000
        of depreciation and the undated 500 must not sneak into the book
        total at full price.
        """
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Configured Laptop',
            price=1000,
            purchase_date='2015-01-01',
        )
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='Undated Laptop',
            price=500,
        )

        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 1500
        assert float(data['total_book_value']) == 0
        assert float(data['total_depreciation']) == 1000
        assert data['asset_count'] == 2
        assert data['depreciable_count'] == 1
        assert data['by_category'][0]['depreciable_count'] == 1

    def test_fleet_valuation_without_configuration_claims_no_financial_value(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        """With nothing configured the fleet reports purchase value only.

        This is the reported case: a new asset with a price and no purchase
        date was read as carrying a book value. There is no configuration
        to strike one from, so the count of depreciable assets is zero, and
        the client hides the financial columns rather than printing a zero.
        """
        _make_item_with_price(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            name='New Laptop',
            price=900,
        )

        response = client.get(
            '/api/v1/equipment/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['total_purchase_value']) == 900
        assert float(data['total_book_value']) == 0
        assert float(data['total_depreciation']) == 0
        assert data['asset_count'] == 1
        assert data['depreciable_count'] == 0
        assert data['by_category'][0]['depreciable_count'] == 0
