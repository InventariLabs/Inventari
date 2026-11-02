"""Every figure this module reports is counted inside one organization.

Stats had no cross-organization test, and it is the module with the most
direct database access in the tree -- three of the escape hatches live here.
Its routes are all reads, which is exactly what makes a leak quiet: nothing
is written, nothing errors, a number is simply larger than it should be.

The shape of every test is the same. A stranger organization is stocked
through the ORM -- items on a shelf, a category, a consumption entry, money
spent -- and then the reader's own organization, which owns none of it, asks
each route what it sees. The expected answer everywhere is "nothing of
theirs".

What these fail on, measured: every ``<Model>.organization_id == <var>``
comparison under ``app/services``, ``app/core/public_api`` and this module
replaced by a tautology (259 of them), which is where these routes actually
scope. All eleven go red. Two things came out of running that the first
time, and both changed the tests rather than the code:

- Four of them asserted that the stranger's *name* was absent from the
  response. Three of those routes answer in counts and totals and never
  print a name, so the assertion held whatever leaked. They now count.
- The suggestion and pattern routes returned nothing at all, because the
  stranger owned one item with no minimum and no purchase history. Empty
  for a reason that has nothing to do with tenancy is not a passing test.
  The stranger now owns enough for both routes to have something to say.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

_MODULES = ['core', 'items', 'locations', 'stats']
_THEIR_ITEM_NAME = 'Stranger Pallet'
_THEIR_CATEGORY_NAME = 'Stranger Goods'
_THEIR_STORAGE_NAME = 'Stranger Warehouse'


@pytest.fixture
def helper(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def stranger_org(helper: ModuleTestHelper) -> Organization:
    return helper.create_org('Strangers Reporting Inc', _MODULES)


@pytest.fixture
def stranger_user(helper: ModuleTestHelper, stranger_org: Organization) -> User:
    return helper.create_user(stranger_org, email='analyst@strangers.example')


@pytest.fixture
def stranger_storage(
    helper: ModuleTestHelper, stranger_org: Organization, stranger_user: User
) -> StorageLocation:
    storage_type = helper.create_storage_type(
        'Stranger Racking', 'STRANGER_RACKING', organization_id=stranger_org.id
    )
    return helper.create_storage_location(
        stranger_org, storage_type, stranger_user, name=_THEIR_STORAGE_NAME
    )


@pytest.fixture
def stranger_stock(
    helper: ModuleTestHelper,
    db_session: Session,
    stranger_org: Organization,
    stranger_user: User,
    stranger_storage: StorageLocation,
) -> Item:
    """Enough of the stranger's data for every route to have something to say.

    Money, quantity, an expiry inside the forecast window, consumption
    history, and a product template sitting below its own minimum — the last
    one so the suggestion route has a reason to fire, rather than staying
    empty for a reason that has nothing to do with tenancy.
    """
    category = Category(name=_THEIR_CATEGORY_NAME, organization_id=stranger_org.id)
    db_session.add(category)
    db_session.flush()

    template = helper.create_template(stranger_org, name=_THEIR_ITEM_NAME)
    template.min_quantity = 100.0
    db_session.add(template)
    db_session.flush()

    item = Item(
        name=_THEIR_ITEM_NAME,
        organization_id=stranger_org.id,
        storage_location_id=stranger_storage.id,
        category_id=category.id,
        template_id=template.id,
        quantity=Decimal('40'),
        purchase_price=Decimal('250.00'),
        expiry_date=(datetime.now(UTC) + timedelta(days=3)).date(),
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.flush()

    # Four more of the same product, because the pattern report only speaks
    # about something bought at least four times. One row would have left it
    # empty for a reason that has nothing to do with tenancy.
    for month in range(1, 5):
        db_session.add(
            Item(
                name=_THEIR_ITEM_NAME,
                organization_id=stranger_org.id,
                storage_location_id=stranger_storage.id,
                category_id=category.id,
                template_id=template.id,
                quantity=Decimal('10'),
                purchase_price=Decimal('250.00'),
                created_at=datetime.now(UTC) - timedelta(days=30 * month),
            )
        )
    db_session.flush()

    for _ in range(4):
        db_session.add(
            ItemHistory(
                item_id=item.id,
                organization_id=stranger_org.id,
                action='USED',
                changes={'quantity': {'from': 40, 'to': 35}},
                user_id=stranger_user.id,
            )
        )
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestTheOverviewCountsOnlyItsOwn:
    def test_their_items_are_not_in_my_totals(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['total_items'] == 0
        assert data['total_locations'] == 1
        assert data['expiring_soon'] == 0


@pytest.mark.integration
class TestTheBreakdownsNameOnlyItsOwn:
    def test_their_storage_is_not_a_row_of_mine(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/by-location', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        names = {row['location_name'] for row in response.json()['items']}
        assert _THEIR_STORAGE_NAME not in names

    def test_their_category_is_not_a_row_of_mine(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/by-category', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        names = {row['category_name'] for row in response.json()['items']}
        assert _THEIR_CATEGORY_NAME not in names

    def test_their_expiry_is_not_on_my_forecast(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/expiry-forecast', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        # The route answers in counts per period, never in names, so asking
        # whether their item is "mentioned" would pass whatever happened.
        assert sum(row['count'] for row in response.json()) == 0


@pytest.mark.integration
class TestTheDerivedReportsStopThereToo:
    def test_their_history_is_not_my_activity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/activity', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _THEIR_ITEM_NAME not in response.text

    def test_their_consumption_is_not_my_consumption(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/consumption', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _THEIR_ITEM_NAME not in response.text

    def test_their_money_is_not_in_my_cost_analysis(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _THEIR_ITEM_NAME not in response.text
        assert _THEIR_CATEGORY_NAME not in response.text

    def test_their_rows_are_not_scanned_by_my_reconciliation(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        """A drift report names no items, so count what it scanned instead."""
        response = client.get('/api/v1/stats/reconciliation', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['items_scanned'] == 0
        assert data['quant_move_drift_count'] == 0
        assert data['layer_quant_drift_count'] == 0

    def test_their_shelf_raises_no_alert_of_mine(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/smart-alerts', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _THEIR_ITEM_NAME not in response.text

    def test_their_purchases_are_not_my_pattern(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['top_recurring_products'] == []
        assert data['seasonal_products'] == []
        assert data['bulk_opportunities'] == []

    def test_their_shelf_suggests_nothing_to_me(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        stranger_stock: Item,
    ) -> None:
        response = client.get(
            '/api/v1/stats/shopping-suggestions', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['items'] == []
