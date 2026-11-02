"""
Integration tests for stock consistency edge cases.

The records are the stock: what a shelf holds is what its live records hold,
summed per group by the records' view. Every change to a record's quantity
writes the movement that explains it, so these tests hold each door to the
second number the stock keeps — the movement ledger must explain the shelf.

Business rules tested:
- Consume/discard cannot result in negative stock
- Quantity updates are validated
- Every quantity change is a movement in the ledger
- Operations on non-existent items are rejected
- Zero and edge quantity values are handled correctly
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow, seed_org_storage_types
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import post_on_shelf


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _on_shelf(db: Session, org_id, template_id, location_id) -> Decimal:
    """What the shelf holds as the records' view sums it; no row is nothing."""
    rows = db.scalars(
        select(ShelfRow).where(
            ShelfRow.organization_id == org_id,
            ShelfRow.product_template_id == template_id,
            ShelfRow.storage_location_id == location_id,
        )
    ).all()
    return sum((row.quantity for row in rows), Decimal('0'))


def _moved_net(db: Session, org_id, template_id, location_id) -> Decimal:
    """What the settled movements net to on the shelf: arrivals less departures."""

    def total(*where) -> Decimal:
        return db.scalar(
            select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
                StockMove.organization_id == org_id,
                StockMove.product_template_id == template_id,
                StockMove.state == 'done',
                *where,
            )
        )

    return total(StockMove.to_location_id == location_id) - total(
        StockMove.from_location_id == location_id
    )


def _assert_consistency(db: Session, org_id, template_id, location_id):
    shelf = _on_shelf(db, org_id, template_id, location_id)
    moved = _moved_net(db, org_id, template_id, location_id)
    assert shelf == moved, (
        f'the ledger does not explain the shelf: shelf={shelf}, moved={moved} '
        f'(template={template_id}, location={location_id})'
    )


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sq_org(db_session: Session) -> Organization:
    org = Organization(
        name='Stock Consistency Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
            'stats',
        ],
    )
    db_session.add(org)
    db_session.flush()
    seed_org_storage_types(db_session, org.id)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def sq_user(db_session: Session, sq_org: Organization) -> User:
    user = User(
        email='sq-test@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='SQ Test User',
        organization_id=sq_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sq_headers(sq_user: User) -> dict:
    return _auth(sq_user)


@pytest.fixture
def sq_storage_type(db_session: Session) -> StorageType:
    st = StorageType(name='Warehouse', type_code='WAREHOUSE', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def sq_location(
    db_session: Session,
    sq_org: Organization,
    sq_storage_type: StorageType,
    sq_user: User,
) -> StorageLocation:
    loc = StorageLocation(
        name='Test Warehouse A',
        organization_id=sq_org.id,
        storage_type_id=sq_storage_type.id,
        created_by=sq_user.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def sq_template(db_session: Session, sq_org: Organization) -> ProductTemplate:
    t = ProductTemplate(
        name='Test Product',
        organization_id=sq_org.id,
        barcode='SQTEST001',
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def sq_seed_item(
    client,
    db_session: Session,
    sq_headers: dict,
    sq_location: StorageLocation,
    sq_template: ProductTemplate,
) -> Item:
    """A record of 100 units, put on the shelf through POST /items."""
    record = post_on_shelf(client, sq_headers, sq_template, sq_location.id, 100)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


# ============================================================================
# Tests: Consume Edge Cases
# ============================================================================


@pytest.mark.integration
class TestConsumeEdgeCases:
    """Tests for consume operation edge cases."""

    def test_consume_exact_quantity_leaves_zero(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """Consuming exact quantity should result in zero stock, not negative."""
        item_id = sq_seed_item.id

        resp = client.patch(
            f'/api/v1/items/{item_id}/consume',
            headers=sq_headers,
            json={'quantity': 100},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()
        db_session.refresh(sq_seed_item)

        assert sq_seed_item.quantity == Decimal('0'), (
            f'Quantity should be 0 after consuming exact amount, got {sq_seed_item.quantity}'
        )
        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)

    def test_consume_zero_quantity_rejected(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """Consuming zero quantity should be rejected (no-op not allowed)."""
        item_id = sq_seed_item.id

        resp = client.patch(
            f'/api/v1/items/{item_id}/consume',
            headers=sq_headers,
            json={'quantity': 0},
        )
        # Should be 422 (validation error) - consuming 0 is not meaningful
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, (
            f'Consuming zero should be rejected, got {resp.status_code}'
        )


# ============================================================================
# Tests: Quantity Update Edge Cases
# ============================================================================


@pytest.mark.integration
class TestQuantityUpdateEdgeCases:
    """Tests for quantity update operation edge cases."""

    def test_update_quantity_to_zero(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """Updating quantity to exactly zero should be valid."""
        item_id = sq_seed_item.id

        resp = client.patch(
            f'/api/v1/items/{item_id}/quantity',
            headers=sq_headers,
            json={'quantity': 0},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()
        db_session.refresh(sq_seed_item)

        assert sq_seed_item.quantity == Decimal('0')
        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)

    def test_update_quantity_to_same_value(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """Updating quantity to same value should be a no-op."""
        item_id = sq_seed_item.id

        resp = client.patch(
            f'/api/v1/items/{item_id}/quantity',
            headers=sq_headers,
            json={'quantity': 100},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)
        assert _on_shelf(
            db_session, sq_org.id, sq_template.id, sq_location.id
        ) == Decimal('100')


# ============================================================================
# Tests: Discard Edge Cases
# ============================================================================


@pytest.mark.integration
class TestDiscardEdgeCases:
    """Tests for discard operation edge cases."""

    def test_discard_exact_quantity(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """Discarding exact quantity should leave zero stock."""
        item_id = sq_seed_item.id

        resp = client.patch(
            f'/api/v1/items/{item_id}/discard',
            headers=sq_headers,
            json={'quantity': 100, 'reason': 'damaged'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()
        db_session.refresh(sq_seed_item)

        assert sq_seed_item.quantity == Decimal('0')
        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)


# ============================================================================
# Tests: Non-existent Items
# ============================================================================


@pytest.mark.integration
class TestNonExistentItems:
    """Tests for operations on non-existent items."""

    def test_consume_nonexistent_item_returns_404(self, client, sq_headers, db_session):
        """Consuming a non-existent item should return 404."""
        fake_id = '00000000-0000-0000-0000-000000000000'

        resp = client.patch(
            f'/api/v1/items/{fake_id}/consume',
            headers=sq_headers,
            json={'quantity': 1},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text

    def test_discard_nonexistent_item_returns_404(self, client, sq_headers, db_session):
        """Discarding a non-existent item should return 404."""
        fake_id = '00000000-0000-0000-0000-000000000000'

        resp = client.patch(
            f'/api/v1/items/{fake_id}/discard',
            headers=sq_headers,
            json={'quantity': 1, 'reason': 'test'},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text

    def test_update_quantity_nonexistent_item_returns_404(
        self, client, sq_headers, db_session
    ):
        """Updating quantity of non-existent item should return 404."""
        fake_id = '00000000-0000-0000-0000-000000000000'

        resp = client.patch(
            f'/api/v1/items/{fake_id}/quantity',
            headers=sq_headers,
            json={'quantity': 50},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text


# ============================================================================
# Tests: Reconciliation Endpoint
# ============================================================================


@pytest.mark.integration
class TestReconciliationEndpoint:
    """Tests for the reconciliation endpoint."""

    def test_reconciliation_reports_zero_drift_for_consistent_data(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """Stock put on the shelf through the door leaves the ledger explaining it.

        The shelf-versus-ledger pair is the one this report still measures
        between two numbers of stock; the records-versus-quant pair ended
        with the quant table.
        """
        resp = client.get('/api/v1/stats/reconciliation', headers=sq_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text

        data = resp.json()
        assert data['quant_move_drift_count'] == 0, (
            f'Reconciliation reported drift: {data}'
        )
        assert data['items_scanned'] == 1, data

    def test_reconciliation_handles_empty_stock(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """Reconciliation should handle locations with zero stock."""
        # First consume all stock
        resp = client.patch(
            f'/api/v1/items/{sq_seed_item.id}/consume',
            headers=sq_headers,
            json={'quantity': 100},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        resp = client.get('/api/v1/stats/reconciliation', headers=sq_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['quant_move_drift_count'] == 0, resp.text


# ============================================================================
# Tests: Item Without Template (meta_data only)
# ============================================================================


@pytest.mark.integration
class TestItemWithoutTemplate:
    """Tests for items that have no template_id (meta_data only items)."""

    def test_item_without_template_creation(
        self, client, sq_headers, db_session, sq_org, sq_location
    ):
        """Items without template_id should follow the system rules."""
        resp = client.post(
            '/api/v1/items',
            headers=sq_headers,
            json={
                'name': 'Meta Only Item',
                'location_id': str(sq_location.id),
                'quantity': 10,
            },
        )
        # template_id is optional and the create path resolves a default one,
        # so an absent template is not a validation error — the item is made.
        assert resp.status_code == status.HTTP_201_CREATED, resp.text


@pytest.mark.integration
class TestPutItemKeepsTheLedger:
    """Regression tests for PUT /items/{id} writing the movement its change is.

    Bug: update_item() modified item.quantity via setattr without calling
    _post_the_change_async(), which is where the change becomes a movement — the
    shelf and the ledger drifted apart in silence.
    """

    def test_put_quantity_change_writes_the_movement(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """PUT /items/{id} with new quantity must write the movement."""
        item_id = sq_seed_item.id

        resp = client.put(
            f'/api/v1/items/{item_id}',
            headers=sq_headers,
            json={'quantity': 50},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()
        db_session.refresh(sq_seed_item)

        assert sq_seed_item.quantity == Decimal('50'), (
            f'Item quantity should be 50, got {sq_seed_item.quantity}'
        )
        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)

    def test_put_quantity_increase_writes_the_movement(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """PUT /items/{id} increasing quantity must write the arrival."""
        item_id = sq_seed_item.id

        resp = client.put(
            f'/api/v1/items/{item_id}',
            headers=sq_headers,
            json={'quantity': 150},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)
        assert _on_shelf(
            db_session, sq_org.id, sq_template.id, sq_location.id
        ) == Decimal('150')

    def test_put_quantity_to_zero_writes_the_movement(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """PUT /items/{id} setting quantity to 0 must write the departure."""
        item_id = sq_seed_item.id

        resp = client.put(
            f'/api/v1/items/{item_id}',
            headers=sq_headers,
            json={'quantity': 0},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)
        assert _on_shelf(
            db_session, sq_org.id, sq_template.id, sq_location.id
        ) == Decimal('0')

    def test_put_non_quantity_field_does_not_affect_the_stock(
        self,
        client,
        sq_headers,
        db_session,
        sq_org,
        sq_template,
        sq_location,
        sq_seed_item,
    ):
        """PUT /items/{id} without quantity change must not touch the stock."""
        item_id = sq_seed_item.id

        resp = client.put(
            f'/api/v1/items/{item_id}',
            headers=sq_headers,
            json={'name': 'Renamed Product'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        _assert_consistency(db_session, sq_org.id, sq_template.id, sq_location.id)
        assert _on_shelf(
            db_session, sq_org.id, sq_template.id, sq_location.id
        ) == Decimal('100')
