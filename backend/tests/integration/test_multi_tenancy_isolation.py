"""
Integration tests for Multi-Tenancy Isolation.

These tests verify that:
- Users can ONLY access data within their own organization
- Cross-organization access attempts are rejected
- Data created by one org is invisible to another org
"""

from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import post_on_shelf


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def org_a(db_session: Session) -> Organization:
    org = Organization(
        name='Organization A',
        enabled_modules=['core', 'items', 'locations', 'categories', 'warehouse'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def org_b(db_session: Session) -> Organization:
    org = Organization(
        name='Organization B',
        enabled_modules=['core', 'items', 'locations', 'categories', 'warehouse'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def user_a(db_session: Session, org_a: Organization) -> User:
    user = User(
        email='user-a@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='User A',
        organization_id=org_a.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def user_b(db_session: Session, org_b: Organization) -> User:
    user = User(
        email='user-b@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='User B',
        organization_id=org_b.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def headers_a(user_a: User) -> dict:
    return _auth(user_a)


@pytest.fixture
def headers_b(user_b: User) -> dict:
    return _auth(user_b)


@pytest.fixture
def storage_type_a(db_session: Session) -> StorageType:
    st = StorageType(name='Warehouse A', type_code='WAREHOUSE_A', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def storage_type_b(db_session: Session) -> StorageType:
    st = StorageType(name='Warehouse B', type_code='WAREHOUSE_B', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def location_a(
    db_session: Session, org_a: Organization, storage_type_a: StorageType, user_a: User
) -> StorageLocation:
    loc = StorageLocation(
        name='Location A',
        organization_id=org_a.id,
        storage_type_id=storage_type_a.id,
        created_by=user_a.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def location_b(
    db_session: Session, org_b: Organization, storage_type_b: StorageType, user_b: User
) -> StorageLocation:
    loc = StorageLocation(
        name='Location B',
        organization_id=org_b.id,
        storage_type_id=storage_type_b.id,
        created_by=user_b.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def template_a(db_session: Session, org_a: Organization) -> ProductTemplate:
    t = ProductTemplate(
        name='Product A',
        organization_id=org_a.id,
        barcode='TEMPLATE-A',
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def template_b(db_session: Session, org_b: Organization) -> ProductTemplate:
    t = ProductTemplate(
        name='Product B',
        organization_id=org_b.id,
        barcode='TEMPLATE-B',
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def item_a(
    client,
    db_session: Session,
    headers_a: dict,
    location_a: StorageLocation,
    template_a: ProductTemplate,
) -> Item:
    """A hundred of product A in organization A's location, entered through POST /items."""
    record = post_on_shelf(client, headers_a, template_a, location_a.id, 100)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


@pytest.fixture
def item_b(
    client,
    db_session: Session,
    headers_b: dict,
    location_b: StorageLocation,
    template_b: ProductTemplate,
) -> Item:
    """Fifty of product B in organization B's location, entered through POST /items."""
    record = post_on_shelf(client, headers_b, template_b, location_b.id, 50)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


@pytest.fixture
def category_b(db_session: Session, org_b: Organization) -> Category:
    cat = Category(
        name='Category B',
        organization_id=org_b.id,
        field_definitions=[{'key': 'secret_field', 'label': 'Secret', 'type': 'text'}],
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


@pytest.fixture
def category_global(db_session: Session) -> Category:
    """Categories may be global (``organization_id IS NULL``) by design."""
    cat = Category(name='Global Category', organization_id=None)
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


@pytest.fixture
def uom_category_b(db_session: Session, org_b: Organization):
    from app.models.uom import UomCategory

    cat = UomCategory(name='Volume B', organization_id=org_b.id)
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


@pytest.fixture
def uom_b(db_session: Session, uom_category_b):
    from decimal import Decimal

    from app.models.uom import Uom

    uom = Uom(
        name='Skrzynka B',
        symbol='skrzB',
        category_id=uom_category_b.id,
        organization_id=uom_category_b.organization_id,
        factor=Decimal('10'),
        rounding=Decimal('1'),
    )
    db_session.add(uom)
    db_session.commit()
    db_session.refresh(uom)
    return uom


@pytest.fixture
def uom_global(db_session: Session):
    """Units may be global (``organization_id IS NULL``) by design."""
    from decimal import Decimal

    from app.models.uom import Uom, UomCategory

    cat = UomCategory(name='Global volume', organization_id=None)
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    uom = Uom(
        name='Global crate',
        symbol='gcr',
        category_id=cat.id,
        organization_id=None,
        factor=Decimal('12'),
        rounding=Decimal('1'),
    )
    db_session.add(uom)
    db_session.commit()
    db_session.refresh(uom)
    return uom


# ============================================================================
# Tests: Category scoping
# ============================================================================


@pytest.mark.integration
class TestCategoryScoping:
    """The item response serialises the whole category, so an unchecked
    ``category_id`` leaked another org's field configuration."""

    def test_create_item_with_foreign_category_returns_404(
        self, client, headers_a, location_a, category_b
    ):
        resp = client.post(
            '/api/v1/items',
            json={
                'name': 'Probe',
                'location_id': str(location_a.id),
                'category_id': str(category_b.id),
            },
            headers=headers_a,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text
        assert 'secret_field' not in resp.text

    def test_create_item_with_global_category_succeeds(
        self, client, headers_a, location_a, category_global
    ):
        resp = client.post(
            '/api/v1/items',
            json={
                'name': 'Probe global',
                'location_id': str(location_a.id),
                'category_id': str(category_global.id),
            },
            headers=headers_a,
        )
        assert resp.status_code in (200, 201), resp.text

    def test_update_item_to_foreign_category_returns_404(
        self, client, headers_a, item_a, category_b
    ):
        resp = client.put(
            f'/api/v1/items/{item_a.id}',
            json={'category_id': str(category_b.id)},
            headers=headers_a,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text

    def test_scan_assign_with_foreign_category_returns_404(
        self, client, headers_a, location_a, category_b
    ):
        """The scan path builds an Item straight from the request — the very
        shape the create guard was written for."""
        resp = client.post(
            '/api/v1/labels/scan/5901234123457/assign',
            json={
                'location_id': str(location_a.id),
                'category_id': str(category_b.id),
                'name': 'Scanned probe',
                'quantity': 1,
            },
            headers=headers_a,
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text
        assert 'secret_field' not in resp.text

    def test_scan_assign_with_global_category_succeeds(
        self, client, headers_a, location_a, category_global
    ):
        resp = client.post(
            '/api/v1/labels/scan/5901234123458/assign',
            json={
                'location_id': str(location_a.id),
                'category_id': str(category_global.id),
                'name': 'Scanned global',
                'quantity': 1,
            },
            headers=headers_a,
        )

        assert resp.status_code in (200, 201), resp.text

    def test_bulk_update_to_foreign_category_returns_404(
        self, client, headers_a, item_a, category_b, db_session
    ):
        resp = client.patch(
            '/api/v1/items/bulk',
            json={
                'item_ids': [str(item_a.id)],
                'update_data': {'category_id': str(category_b.id)},
            },
            headers=headers_a,
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text
        db_session.refresh(item_a)
        assert item_a.category_id is None, 'the batch must not have been applied'

    def test_bulk_update_to_global_category_succeeds(
        self, client, headers_a, item_a, category_global, db_session
    ):
        """Control for the test above: the guard rejects the foreign category,
        not every category."""
        resp = client.patch(
            '/api/v1/items/bulk',
            json={
                'item_ids': [str(item_a.id)],
                'update_data': {'category_id': str(category_global.id)},
            },
            headers=headers_a,
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.refresh(item_a)
        assert item_a.category_id == category_global.id


@pytest.mark.integration
class TestUomScoping:
    """The item response embeds the unit (symbol, factor), so an unchecked
    ``uom_id`` read another org's unit definition and converted quantities
    on its factor. The category on the same request was guarded; the unit,
    until the guard these tests pin, was not."""

    def test_create_item_with_foreign_uom_returns_404(
        self, client, headers_a, location_a, uom_b
    ):
        resp = client.post(
            '/api/v1/items',
            json={
                'name': 'Probe unit',
                'location_id': str(location_a.id),
                'uom_id': str(uom_b.id),
            },
            headers=headers_a,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text
        assert uom_b.symbol not in resp.text

    def test_create_item_with_global_uom_succeeds(
        self, client, headers_a, location_a, uom_global
    ):
        resp = client.post(
            '/api/v1/items',
            json={
                'name': 'Probe unit global',
                'location_id': str(location_a.id),
                'uom_id': str(uom_global.id),
            },
            headers=headers_a,
        )
        assert resp.status_code in (200, 201), resp.text

    def test_update_item_to_foreign_uom_returns_404(
        self, client, headers_a, item_a, uom_b, db_session
    ):
        resp = client.put(
            f'/api/v1/items/{item_a.id}',
            json={'uom_id': str(uom_b.id)},
            headers=headers_a,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text
        db_session.refresh(item_a)
        assert item_a.uom_id != uom_b.id, 'the unit must not have been applied'

    def test_bulk_update_to_foreign_uom_returns_404(
        self, client, headers_a, item_a, uom_b, db_session
    ):
        resp = client.patch(
            '/api/v1/items/bulk',
            json={
                'item_ids': [str(item_a.id)],
                'update_data': {'uom_id': str(uom_b.id)},
            },
            headers=headers_a,
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text
        db_session.refresh(item_a)
        assert item_a.uom_id != uom_b.id, 'the batch must not have been applied'


# ============================================================================
# Tests: Items Isolation
# ============================================================================


@pytest.mark.integration
class TestItemsIsolation:
    """Tests that items are isolated by organization."""

    def test_user_a_sees_only_org_a_items(self, client, headers_a, item_a, item_b):
        """User A should only see items from Organization A."""
        resp = client.get('/api/v1/items', headers=headers_a)
        assert resp.status_code == status.HTTP_200_OK, resp.text

        data = resp.json()
        # Handle both list response and paginated response
        if isinstance(data, dict):
            items = data.get('items', data.get('data', []))
        else:
            items = data if isinstance(data, list) else []

        item_ids = [item['id'] for item in items]

        # Item A should be visible
        assert str(item_a.id) in item_ids, 'User A should see their own items'

        # BUG DETECTION: If item B is visible, that's a security issue
        if str(item_b.id) in item_ids:
            raise AssertionError(
                'CRITICAL: User A can see items from Org B - tenant isolation violated'
            )

    def test_user_b_sees_only_org_b_items(self, client, headers_b, item_a, item_b):
        """User B should only see items from Organization B."""
        resp = client.get('/api/v1/items', headers=headers_b)
        assert resp.status_code == status.HTTP_200_OK, resp.text

        data = resp.json()
        if isinstance(data, dict):
            items = data.get('items', data.get('data', []))
        else:
            items = data if isinstance(data, list) else []

        item_ids = [item['id'] for item in items]

        # Item B should be visible
        assert str(item_b.id) in item_ids, 'User B should see their own items'

        # BUG DETECTION
        if str(item_a.id) in item_ids:
            raise AssertionError(
                'CRITICAL: User B can see items from Org A - tenant isolation violated'
            )

    def test_user_a_cannot_access_item_b_directly(self, client, headers_a, item_b):
        """User A should get 404 when accessing item B directly."""
        resp = client.get(f'/api/v1/items/{item_b.id}', headers=headers_a)
        # BUG DETECTION: Should be 404, if 200/403/any other success - it's a bug
        if resp.status_code == status.HTTP_200_OK:
            raise AssertionError(
                'CRITICAL: User A can directly access item B - security violation'
            )
        # Expected: 404 Not Found
        assert resp.status_code == status.HTTP_404_NOT_FOUND, (
            f'Expected 404 for cross-org access, got {resp.status_code}'
        )


# ============================================================================
# Tests: Storage Locations Isolation
# ============================================================================


@pytest.mark.integration
class TestStorageLocationsIsolation:
    """Tests that storage locations are isolated by organization."""

    def test_user_a_sees_only_org_a_locations(
        self, client, headers_a, location_a, location_b
    ):
        """User A should only see locations from Organization A."""
        resp = client.get('/api/v1/locations', headers=headers_a)
        assert resp.status_code == status.HTTP_200_OK, resp.text

        data = resp.json()
        # Handle paginated response
        if isinstance(data, dict):
            locations = data.get('items', data.get('data', []))
        else:
            locations = data if isinstance(data, list) else []

        location_ids = [loc['id'] for loc in locations]

        assert str(location_a.id) in location_ids, (
            'User A should see their own locations'
        )

        # BUG DETECTION
        if str(location_b.id) in location_ids:
            raise AssertionError('CRITICAL: User A can see locations from Org B')


# ============================================================================
# Tests: Storage Types Isolation
# ============================================================================


@pytest.mark.integration
class TestStorageTypesIsolation:
    """The org a storage type lands in comes from the token, not the payload."""

    def test_create_ignores_organization_id_from_body(
        self, client, headers_a, user_a, org_b, db_session
    ):
        resp = client.post(
            '/api/v1/location-types',
            json={
                'name': 'Planted Type',
                'type_code': 'PLANTED',
                'organization_id': str(org_b.id),
            },
            headers=headers_a,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        created = (
            db_session.query(StorageType)
            .filter(StorageType.type_code == 'PLANTED')
            .one()
        )
        assert created.organization_id == user_a.organization_id
        assert created.organization_id != org_b.id

    def test_planted_type_is_invisible_to_the_targeted_org(
        self, client, headers_a, headers_b, org_b
    ):
        client.post(
            '/api/v1/location-types',
            json={
                'name': 'Planted Type 2',
                'type_code': 'PLANTED2',
                'organization_id': str(org_b.id),
            },
            headers=headers_a,
        )

        resp = client.get('/api/v1/location-types', headers=headers_b)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert 'PLANTED2' not in {st['type_code'] for st in resp.json()['items']}


# ============================================================================
# Tests: Product Templates Isolation
# ============================================================================


@pytest.mark.integration
class TestProductTemplatesIsolation:
    """Tests that product templates are isolated by organization."""

    def test_user_a_sees_only_org_a_templates(
        self, client, headers_a, template_a, template_b
    ):
        """User A should only see templates from Organization A.

        This asked `/api/v1/product-templates`, a route that never existed, and
        skipped on the 404 — so tenant isolation of templates was checked by
        nothing. Both names match the search, so a leak cannot hide behind it.
        """
        resp = client.get(
            '/api/v1/items/product-templates',
            params={'search': 'Product', 'limit': 50},
            headers=headers_a,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        template_ids = {t['id'] for t in resp.json()}
        assert str(template_a.id) in template_ids, (
            'User A should see their own templates'
        )
        assert str(template_b.id) not in template_ids, (
            'CRITICAL: User A can see templates from Org B'
        )


# ============================================================================
# Tests: Unauthorized Access (no auth headers)
# ============================================================================


@pytest.mark.integration
class TestUnauthorizedAccess:
    """Tests for access without authentication."""

    def test_missing_auth_returns_401(self, client):
        """Request without auth headers should return 401."""
        resp = client.get('/api/v1/items')
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED, resp.text

    def test_invalid_token_returns_401(self, client):
        """Request with invalid token should return 401."""
        resp = client.get(
            '/api/v1/items',
            headers={'Authorization': 'Bearer invalid_token'},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED, resp.text


# ============================================================================
# A foreign shelf is not a destination
# ============================================================================


@pytest.mark.integration
class TestItemCannotBeParkedOnAForeignShelf:
    """``storage_location_id`` decides who can see a record.

    Creating an item validates the location it names; updating it did not —
    the id fell through to a plain ``setattr``. Since the list and the detail
    fetch are scoped by the locations the caller owns, a record moved onto
    another organization's shelf became that organization's to read and to
    write, and its stock quant followed it across the boundary.
    """

    def test_update_refuses_a_location_owned_by_another_org(
        self, client, headers_a, item_a, location_b
    ):
        resp = client.put(
            f'/api/v1/items/{item_a.id}',
            headers=headers_a,
            json={'location_id': str(location_b.id)},
        )

        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
        ), resp.text

    def test_the_refused_update_leaves_the_record_where_it_was(
        self, client, headers_a, headers_b, item_a, location_a, location_b
    ):
        client.put(
            f'/api/v1/items/{item_a.id}',
            headers=headers_a,
            json={'location_id': str(location_b.id)},
        )

        # Still A's, and still invisible to B — which is the whole point.
        mine = client.get(f'/api/v1/items/{item_a.id}', headers=headers_a)
        assert mine.status_code == status.HTTP_200_OK, mine.text
        assert mine.json()['location_id'] == str(location_a.id)

        theirs = client.get(f'/api/v1/items/{item_a.id}', headers=headers_b)
        assert theirs.status_code == status.HTTP_404_NOT_FOUND

    def test_bulk_update_refuses_it_too(
        self, client, headers_a, item_a, location_a, location_b
    ):
        resp = client.patch(
            '/api/v1/items/bulk',
            headers=headers_a,
            json={
                'item_ids': [str(item_a.id)],
                'update_data': {'location_id': str(location_b.id)},
            },
        )

        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
        ), resp.text

        still_here = client.get(f'/api/v1/items/{item_a.id}', headers=headers_a)
        assert still_here.json()['location_id'] == str(location_a.id)

    def test_a_second_location_of_my_own_is_still_accepted(
        self,
        client,
        db_session: Session,
        headers_a,
        org_a,
        user_a,
        storage_type_a,
        location_a,
        template_a,
    ):
        """The guard refuses the foreign shelf, not the legitimate move."""
        # A record the application wrote, so the register holds what it holds:
        # the move carries it across.
        record = post_on_shelf(client, headers_a, template_a, location_a.id, 100)
        other_mine = StorageLocation(
            name='Location A2',
            organization_id=org_a.id,
            storage_type_id=storage_type_a.id,
            created_by=user_a.id,
        )
        db_session.add(other_mine)
        db_session.commit()
        db_session.refresh(other_mine)

        resp = client.put(
            f'/api/v1/items/{record["id"]}',
            headers=headers_a,
            json={'location_id': str(other_mine.id)},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['location_id'] == str(other_mine.id)
