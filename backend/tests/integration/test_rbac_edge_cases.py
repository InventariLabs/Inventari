"""
Integration tests for RBAC (Role-Based Access Control) edge cases.

These tests verify that:
- User role cannot perform admin actions
- Module-level permissions are enforced
- Disabled modules reject access to their endpoints
- Role hierarchy is respected
"""

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import anchor_pending_records


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def rbac_org(db_session: Session) -> Organization:
    org = Organization(
        name='RBAC Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
            'stock_takes',
            'stats',
            'equipment',
        ],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def rbac_admin(db_session: Session, rbac_org: Organization) -> User:
    user = User(
        email='rbac-admin@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='RBAC Admin',
        organization_id=rbac_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def rbac_user(db_session: Session, rbac_org: Organization) -> User:
    user = User(
        email='rbac-user@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='RBAC Regular User',
        organization_id=rbac_org.id,
        role='user',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def rbac_viewer(db_session: Session, rbac_org: Organization) -> User:
    user = User(
        email='rbac-viewer@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='RBAC Viewer',
        organization_id=rbac_org.id,
        role='viewer',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def rbac_admin_headers(rbac_admin: User) -> dict:
    return _auth(rbac_admin)


@pytest.fixture
def rbac_user_headers(rbac_user: User) -> dict:
    return _auth(rbac_user)


@pytest.fixture
def rbac_viewer_headers(rbac_viewer: User) -> dict:
    return _auth(rbac_viewer)


@pytest.fixture
def rbac_storage_type(db_session: Session) -> StorageType:
    st = StorageType(name='RBAC Warehouse', type_code='RBAC_WH', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def rbac_location(
    db_session: Session,
    rbac_org: Organization,
    rbac_storage_type: StorageType,
    rbac_admin: User,
) -> StorageLocation:
    loc = StorageLocation(
        name='RBAC Test Location',
        organization_id=rbac_org.id,
        storage_type_id=rbac_storage_type.id,
        created_by=rbac_admin.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def rbac_template(db_session: Session, rbac_org: Organization) -> ProductTemplate:
    t = ProductTemplate(
        name='RBAC Test Product',
        organization_id=rbac_org.id,
        barcode='RBAC001',
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def rbac_item(
    db_session: Session,
    rbac_org: Organization,
    rbac_location: StorageLocation,
    rbac_template: ProductTemplate,
) -> Item:
    item = Item(
        name='RBAC Test Item',
        organization_id=rbac_org.id,
        storage_location_id=rbac_location.id,
        template_id=rbac_template.id,
        quantity=Decimal('100'),
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.commit()
    db_session.refresh(item)
    return item


# ============================================================================
# Tests: User Role - Read Operations
# ============================================================================


@pytest.mark.integration
class TestUserRoleReadOperations:
    """Tests that regular users can perform read operations."""

    def test_user_can_read_items(self, client, rbac_user_headers, rbac_item):
        """Regular user should be able to read items."""
        resp = client.get('/api/v1/items', headers=rbac_user_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def test_user_can_read_item_details(self, client, rbac_user_headers, rbac_item):
        """Regular user should be able to read item details."""
        resp = client.get(f'/api/v1/items/{rbac_item.id}', headers=rbac_user_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text


# ============================================================================
# Tests: Viewer Role - Read Only Access
# ============================================================================


@pytest.mark.integration
class TestViewerRoleReadOnly:
    """Tests that viewers have read-only access."""

    def test_viewer_can_read_items(self, client, rbac_viewer_headers, rbac_item):
        """Viewer should be able to read items."""
        resp = client.get('/api/v1/items', headers=rbac_viewer_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def test_viewer_cannot_create_items(
        self, client, rbac_viewer_headers, rbac_location
    ):
        """Viewer should NOT be able to create items."""
        resp = client.post(
            '/api/v1/items',
            headers=rbac_viewer_headers,
            json={
                'name': 'Viewer Created Item',
                'location_id': str(rbac_location.id),
                'quantity': 1,
            },
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, (
            f'Expected 403 but got {resp.status_code}: {resp.text}'
        )

    def test_viewer_cannot_update_items(self, client, rbac_viewer_headers, rbac_item):
        """Viewer should NOT be able to update items."""
        resp = client.patch(
            f'/api/v1/items/{rbac_item.id}/quantity',
            headers=rbac_viewer_headers,
            json={'quantity': 50},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, (
            f'Expected 403 but got {resp.status_code}: {resp.text}'
        )


# ============================================================================
# Tests: Admin Role - Full Access
# ============================================================================


@pytest.mark.integration
class TestAdminRoleFullAccess:
    """Tests that admin role can perform all actions."""

    def test_admin_can_create_items(self, client, rbac_admin_headers, rbac_location):
        """Admin should be able to create items."""
        resp = client.post(
            '/api/v1/items',
            headers=rbac_admin_headers,
            json={
                'name': 'Admin Created Item',
                'location_id': str(rbac_location.id),
                'quantity': 10,
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_admin_can_update_items(self, client, rbac_admin_headers, rbac_item):
        """Admin should be able to update items."""
        resp = client.patch(
            f'/api/v1/items/{rbac_item.id}/quantity',
            headers=rbac_admin_headers,
            json={'quantity': 50},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def test_admin_can_delete_items(self, client, rbac_admin_headers, rbac_location):
        """Admin should be able to delete items."""
        # Create item first
        resp = client.post(
            '/api/v1/items',
            headers=rbac_admin_headers,
            json={
                'name': 'Admin Delete Item',
                'location_id': str(rbac_location.id),
                'quantity': 10,
            },
        )
        item_id = resp.json()['id']

        resp = client.delete(f'/api/v1/items/{item_id}', headers=rbac_admin_headers)
        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.text


# ============================================================================
# Tests: Stock Operations Permissions
# ============================================================================


@pytest.mark.integration
class TestStockOperationsPermissions:
    """Tests for stock operation permissions."""

    def test_user_can_consume(self, client, rbac_user_headers, rbac_item):
        """Regular user should be able to consume items."""
        resp = client.patch(
            f'/api/v1/items/{rbac_item.id}/consume',
            headers=rbac_user_headers,
            json={'quantity': 5},
        )
        # The 422 on this route comes from the UOM precision check, and the
        # rbac_item fixture sets no uom_id, so that branch cannot fire here.
        # A member may consume: that is the whole claim.
        assert resp.status_code == 200, resp.text

    def test_viewer_cannot_consume(self, client, rbac_viewer_headers, rbac_item):
        """Viewer should NOT be able to consume items."""
        resp = client.patch(
            f'/api/v1/items/{rbac_item.id}/consume',
            headers=rbac_viewer_headers,
            json={'quantity': 5},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, (
            f'Expected 403 but got {resp.status_code}: {resp.text}'
        )


# ============================================================================
# Tests: Module-Level Permissions
# ============================================================================


@pytest.mark.integration
class TestModulePermissions:
    """Tests for module-level permission enforcement."""

    def test_disabled_module_rejects_access(
        self, client, rbac_admin_headers, db_session, rbac_org
    ):
        """Endpoints for disabled modules should return 403 or 404."""
        # Disable equipment module for the org
        original_modules = list(rbac_org.enabled_modules)
        rbac_org.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
        ]
        db_session.commit()

        try:
            # Try to access equipment endpoints
            resp = client.get('/api/v1/equipment/items', headers=rbac_admin_headers)
            # BUG DETECTION: If we get 200, the module guard is not working
            if resp.status_code == status.HTTP_200_OK:
                raise AssertionError(
                    'BUG DETECTED: Disabled module is still accessible - module guard not working'
                )
        finally:
            # Restore modules
            rbac_org.enabled_modules = original_modules
            db_session.commit()
