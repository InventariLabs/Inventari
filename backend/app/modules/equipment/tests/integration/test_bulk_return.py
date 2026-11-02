"""
Integration tests for the bulk return endpoint.

POST /equipment/items/bulk-return checks in every selected asset that has
an active assignment, with one condition for the whole batch — the leaving
employee scenario (five devices back at once).
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
from app.modules.equipment.models import EquipmentAssignment
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def eq_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Bulk Return Org',
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
        full_name='Bulk Return User',
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
    cat = Category(
        name='Laptop',
        code='LAPTOP',
        context_tag='equipment',
        organization_id=None,
        field_definitions=[],
    )
    real_async_db_session.add(cat)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(cat)
    return cat


@pytest.fixture
async def eq_items(
    real_async_db_session: AsyncSession,
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
) -> list[Item]:
    items = []
    for i in range(3):
        item = Item(
            name=f'Asset {i}',
            organization_id=eq_org.id,
            storage_location_id=eq_storage_location.id,
            category_id=eq_category.id,
            quantity=1,
            meta_data={
                'equipment': {
                    'serial_number': f'SN-{i}',
                    'equipment_status': 'AVAILABLE',
                }
            },
        )
        real_async_db_session.add(item)
        items.append(item)
    await real_async_db_session.commit()
    for item in items:
        await real_async_db_session.refresh(item)
    return items


async def _checkout(client: AsyncClient, user: User, item: Item) -> None:
    response = await client.post(
        '/api/v1/equipment/assignments',
        headers=_auth(user),
        json={'item_id': str(item.id), 'assigned_to_name': 'Anna Kowalska'},
    )
    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.integration
@pytest.mark.asyncio
class TestBulkReturn:
    async def test_bulk_return_checks_in_assigned_items(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_items: list[Item],
    ) -> None:
        await _checkout(real_async_client, eq_user, eq_items[0])
        await _checkout(real_async_client, eq_user, eq_items[1])

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-return',
            headers=_auth(eq_user),
            json={
                'item_ids': [str(i.id) for i in eq_items],
                'checkin_condition': 'GOOD',
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['checked_in'] == 2
        assert len(data['errors']) == 1
        assert data['errors'][0]['item_id'] == str(eq_items[2].id)

        assignments = (
            await real_async_db_session.scalars(
                select(EquipmentAssignment).where(
                    EquipmentAssignment.organization_id == eq_user.organization_id
                )
            )
        ).all()
        checked_in = [a for a in assignments if a.checked_in_at is not None]
        assert len(checked_in) == 2
        assert all(a.checkin_condition == 'GOOD' for a in checked_in)

    async def test_bulk_return_damaged_sets_maintenance(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_items: list[Item],
    ) -> None:
        await _checkout(real_async_client, eq_user, eq_items[0])

        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-return',
            headers=_auth(eq_user),
            json={
                'item_ids': [str(eq_items[0].id)],
                'checkin_condition': 'DAMAGED',
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['checked_in'] == 1

        await real_async_db_session.refresh(eq_items[0])
        assert (eq_items[0].meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'MAINTENANCE'

    async def test_bulk_return_item_without_assignment_reports_error(
        self,
        real_async_client: AsyncClient,
        eq_user: User,
        eq_items: list[Item],
    ) -> None:
        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-return',
            headers=_auth(eq_user),
            json={
                'item_ids': [str(eq_items[0].id)],
                'checkin_condition': 'GOOD',
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['checked_in'] == 0
        assert len(data['errors']) == 1
        assert data['errors'][0]['item_id'] == str(eq_items[0].id)
        assert data['errors'][0]['code'] == 'ASSIGNMENT_NOT_FOUND'

    async def test_bulk_return_invalid_condition_returns_422(
        self,
        real_async_client: AsyncClient,
        eq_user: User,
        eq_items: list[Item],
    ) -> None:
        response = await real_async_client.post(
            '/api/v1/equipment/items/bulk-return',
            headers=_auth(eq_user),
            json={
                'item_ids': [str(eq_items[0].id)],
                'checkin_condition': 'NOT_A_CONDITION',
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
