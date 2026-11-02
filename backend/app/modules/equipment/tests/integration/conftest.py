"""Fixtures for equipment module integration tests."""

import pytest
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def eq_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Equipment Test Org',
        ['core', 'items', 'locations', 'categories', 'equipment'],
    )


@pytest.fixture
def eq_user(h: ModuleTestHelper, eq_org: Organization) -> User:
    return h.create_user(eq_org, email='equipment@example.com')


@pytest.fixture
def eq_auth_headers(h: ModuleTestHelper, eq_user: User) -> dict[str, str]:
    return h.get_auth_headers(eq_user)


@pytest.fixture
def eq_storage_type(h: ModuleTestHelper) -> StorageType:
    return h.create_storage_type('IT Storage', 'IT_STORAGE')


@pytest.fixture
def eq_storage_location(
    h: ModuleTestHelper,
    eq_org: Organization,
    eq_storage_type: StorageType,
    eq_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        eq_org, eq_storage_type, eq_user, name='Server Room A'
    )


@pytest.fixture
def eq_category(db_session: Session) -> Category:
    """System-level LAPTOP category."""
    cat = Category(
        name='Laptop',
        code='LAPTOP',
        context_tag='equipment',
        organization_id=None,
        field_definitions=[
            {
                'key': 'serial_number',
                'type': 'text',
                'label': 'Serial Number',
                'is_system': True,
            },
            {
                'key': 'warranty_until',
                'type': 'date',
                'label': 'Warranty Until',
                'is_system': True,
            },
            {
                'key': 'equipment_status',
                'type': 'select',
                'label': 'Status',
                'is_system': True,
            },
        ],
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


@pytest.fixture
def eq_item(
    db_session: Session,
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
) -> Item:
    """A laptop asset item in equipment org."""
    item = Item(
        name='ThinkPad X1 Carbon',
        organization_id=eq_org.id,
        storage_location_id=eq_storage_location.id,
        category_id=eq_category.id,
        quantity=1,
        meta_data={
            'equipment': {'serial_number': 'SN-001', 'equipment_status': 'AVAILABLE'}
        },
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item
