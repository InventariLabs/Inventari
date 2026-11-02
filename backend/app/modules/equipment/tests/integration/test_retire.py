"""
Integration tests for equipment retire / bulk-retire / bulk-purge endpoints.

Covers:
- POST /equipment/items/{item_id}/retire
- POST /equipment/items/bulk-retire
- POST /equipment/items/bulk-purge
"""

from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def eq_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Equipment Test Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'equipment'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def eq_user(real_async_db_session: AsyncSession, eq_org: Organization) -> User:
    user = User(
        email=f'eq_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Equipment User',
        organization_id=eq_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def eq_storage_type(real_async_db_session: AsyncSession) -> StorageType:
    st = StorageType(name='IT Storage', type_code='IT_STORAGE', behavior_mode='NONE')
    real_async_db_session.add(st)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(st)
    return st


@pytest.fixture
async def eq_storage_location(
    real_async_db_session: AsyncSession,
    eq_org: Organization,
    eq_storage_type: StorageType,
    eq_user: User,
) -> StorageLocation:
    loc = StorageLocation(
        organization_id=eq_org.id,
        created_by=eq_user.id,
        storage_type_id=eq_storage_type.id,
        name='Server Room A',
    )
    real_async_db_session.add(loc)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(loc)
    return loc


@pytest.fixture
async def eq_category(real_async_db_session: AsyncSession) -> Category:
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
    real_async_db_session.add(cat)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(cat)
    return cat


@pytest.fixture
async def eq_item(
    real_async_db_session: AsyncSession,
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
    real_async_db_session.add(item)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(item)
    return item


@pytest.mark.integration
@pytest.mark.asyncio
class TestRetireEquipment:
    async def test_retire_success(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        response = await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item.id}/retire',
            headers=_auth(eq_user),
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        await real_async_db_session.refresh(eq_item)
        # retiring sets the RETIRED status — the asset stays in the
        # register (and in the dashboard "retired" tile), it is NOT archived.
        assert eq_item.is_deleted is False
        assert (eq_item.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'RETIRED'
        assert eq_item.quantity == 1

    async def test_retire_nonexistent_returns_404(
        self, real_async_client: AsyncClient, eq_user: User
    ) -> None:
        response = await real_async_client.post(
            f'/api/v1/equipment/items/{uuid4()}/retire',
            headers=_auth(eq_user),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_retire_double_returns_error(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item.id}/retire',
            headers=_auth(eq_user),
        )

        response = await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item.id}/retire',
            headers=_auth(eq_user),
        )

        # RETIRED -> RETIRED is not a valid transition.
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_retire_keeps_item_in_list(
        self, real_async_client: AsyncClient, eq_user: User, eq_item: Item
    ) -> None:
        await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item.id}/retire',
            headers=_auth(eq_user),
        )

        response = await real_async_client.get('/api/v1/items', headers=_auth(eq_user))
        data = response.json()
        assert any(i['id'] == str(eq_item.id) for i in data['items'])

    async def test_retire_does_not_show_in_archived(
        self, real_async_client: AsyncClient, eq_user: User, eq_item: Item
    ) -> None:
        await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item.id}/retire',
            headers=_auth(eq_user),
        )

        response = await real_async_client.get(
            '/api/v1/items/archived', headers=_auth(eq_user)
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert all(i['id'] != str(eq_item.id) for i in data)


@pytest.mark.integration
@pytest.mark.asyncio
class TestBulkRetire:
    async def test_bulk_retire_success(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_item: Item,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        item2 = Item(
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=eq_category.id,
            name='Dell Latitude',
            quantity=1,
        )
        real_async_db_session.add(item2)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(item2)

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-retire',
            headers=_auth(eq_user),
            json=[str(eq_item.id), str(item2.id)],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['retired'] == 2
        assert data['errors'] == []

        await real_async_db_session.refresh(eq_item)
        await real_async_db_session.refresh(item2)
        assert eq_item.is_deleted is False
        assert (eq_item.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'RETIRED'
        assert item2.is_deleted is False
        assert (item2.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'RETIRED'

    async def test_bulk_retire_skips_not_found(
        self, real_async_client: AsyncClient, eq_user: User, eq_item: Item
    ) -> None:
        fake_id = uuid4()

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-retire',
            headers=_auth(eq_user),
            json=[str(eq_item.id), str(fake_id)],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['retired'] == 1
        # The row speaks the 404's sentence and code; it used to carry the
        # envelope's repr, braces and quotes included.
        assert data['errors'] == [
            {
                'item_id': str(fake_id),
                'error': 'Item not found',
                'code': 'ITEM_NOT_FOUND',
            }
        ]


@pytest.mark.integration
@pytest.mark.asyncio
class TestBulkPurge:
    async def test_bulk_purge_success(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_item: Item,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        eq_item_id = eq_item.id

        await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item_id}/archive',
            headers=_auth(eq_user),
        )

        item2 = Item(
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=eq_category.id,
            name='MacBook Pro',
            quantity=1,
            is_deleted=True,
            deletion_reason='ARCHIVED',
        )
        real_async_db_session.add(item2)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(item2)
        item2_id = item2.id

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-purge',
            headers=_auth(eq_user),
            json=[str(eq_item_id), str(item2_id)],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['purged'] == 2
        assert data['errors'] == []

        assert (
            await real_async_db_session.scalars(
                select(Item).where(Item.id == eq_item_id)
            )
        ).first() is None
        assert (
            await real_async_db_session.scalars(select(Item).where(Item.id == item2_id))
        ).first() is None

    async def test_bulk_purge_rejects_active(
        self, real_async_client: AsyncClient, eq_user: User, eq_item: Item
    ) -> None:
        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-purge',
            headers=_auth(eq_user),
            json=[str(eq_item.id)],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['purged'] == 0
        assert len(data['errors']) == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestArchiveEquipment:
    """archiving is the soft delete; retiring only sets the status."""

    async def test_archive_success(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        response = await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item.id}/archive',
            headers=_auth(eq_user),
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        await real_async_db_session.refresh(eq_item)
        assert eq_item.is_deleted is True
        assert eq_item.deletion_reason == 'ARCHIVED'
        assert eq_item.deleted_at is not None
        assert eq_item.quantity == 0

    async def test_archive_nonexistent_returns_404(
        self, real_async_client: AsyncClient, eq_user: User
    ) -> None:
        response = await real_async_client.post(
            f'/api/v1/equipment/items/{uuid4()}/archive',
            headers=_auth(eq_user),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_archive_shows_in_archived(
        self, real_async_client: AsyncClient, eq_user: User, eq_item: Item
    ) -> None:
        await real_async_client.post(
            f'/api/v1/equipment/items/{eq_item.id}/archive',
            headers=_auth(eq_user),
        )

        response = await real_async_client.get(
            '/api/v1/items/archived', headers=_auth(eq_user)
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        archived = next(i for i in data if i['id'] == str(eq_item.id))
        assert archived['deletion_reason'] == 'ARCHIVED'

    async def test_bulk_archive_success(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_item: Item,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
    ) -> None:
        item2 = Item(
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=eq_category.id,
            name='Dell Latitude',
            quantity=1,
        )
        real_async_db_session.add(item2)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(item2)

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-archive',
            headers=_auth(eq_user),
            json=[str(eq_item.id), str(item2.id)],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['archived'] == 2
        assert data['errors'] == []

        await real_async_db_session.refresh(eq_item)
        await real_async_db_session.refresh(item2)
        assert eq_item.is_deleted is True
        assert eq_item.deletion_reason == 'ARCHIVED'
        assert item2.is_deleted is True
        assert item2.deletion_reason == 'ARCHIVED'

    async def test_bulk_archive_skips_not_found(
        self, real_async_client: AsyncClient, eq_user: User, eq_item: Item
    ) -> None:
        fake_id = uuid4()

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-archive',
            headers=_auth(eq_user),
            json=[str(eq_item.id), str(fake_id)],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['archived'] == 1
        assert len(data['errors']) == 1
        assert data['errors'][0]['item_id'] == str(fake_id)


@pytest.fixture
async def assigned_item(
    real_async_db_session: AsyncSession,
    eq_org: Organization,
    eq_user: User,
    eq_item: Item,
) -> Item:
    """``eq_item`` with an open (not checked-in) assignment."""
    from app.modules.equipment.models import EquipmentAssignment

    eq_item.meta_data = {
        'equipment': {'serial_number': 'SN-001', 'equipment_status': 'DEPLOYED'}
    }
    real_async_db_session.add(
        EquipmentAssignment(
            organization_id=eq_org.id,
            item_id=eq_item.id,
            assigned_to_name='Anna Kowalska',
            assigned_to_email='anna.kowalska@example.org',
            checked_out_by=eq_user.id,
        )
    )
    await real_async_db_session.commit()
    await real_async_db_session.refresh(eq_item)
    return eq_item


@pytest.mark.integration
@pytest.mark.asyncio
class TestAssignedAssetCannotLeaveTheRegisterSilently:
    """An asset someone still holds cannot be archived or retired.

    Archiving is a soft delete, so the assignment interceptor rejects it —
    the endpoint must translate that into 409, not leak a 500. Retiring
    changes the status instead of deleting, so it needs its own guard:
    without it the asset counts as DEPLOYED and RETIRED at once, and the
    later check-in silently resets the status back to AVAILABLE.
    """

    async def test_archive_assigned_returns_409(
        self,
        real_async_client: AsyncClient,
        eq_user: User,
        assigned_item: Item,
    ) -> None:
        response = await real_async_client.post(
            f'/api/v1/equipment/items/{assigned_item.id}/archive',
            headers=_auth(eq_user),
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert response.json()['detail']['code'] == 'EQUIPMENT_ASSIGNED'

    async def test_bulk_archive_assigned_reports_error_not_500(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        assigned_item: Item,
    ) -> None:
        free_item = Item(
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=eq_category.id,
            name='Dell Latitude',
            quantity=1,
        )
        real_async_db_session.add(free_item)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(free_item)

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-archive',
            headers=_auth(eq_user),
            json=[str(assigned_item.id), str(free_item.id)],
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['archived'] == 1
        assert len(data['errors']) == 1
        assert data['errors'][0]['item_id'] == str(assigned_item.id)
        assert data['errors'][0]['code'] == 'EQUIPMENT_ASSIGNED'

    async def test_retire_assigned_returns_409(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        assigned_item: Item,
    ) -> None:
        response = await real_async_client.post(
            f'/api/v1/equipment/items/{assigned_item.id}/retire',
            headers=_auth(eq_user),
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert response.json()['detail']['code'] == 'EQUIPMENT_ASSIGNED'

        await real_async_db_session.refresh(assigned_item)
        assert (assigned_item.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'DEPLOYED'

    async def test_bulk_retire_assigned_reports_error(
        self,
        real_async_client: AsyncClient,
        eq_user: User,
        assigned_item: Item,
    ) -> None:
        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-retire',
            headers=_auth(eq_user),
            json=[str(assigned_item.id)],
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['retired'] == 0
        assert len(data['errors']) == 1
