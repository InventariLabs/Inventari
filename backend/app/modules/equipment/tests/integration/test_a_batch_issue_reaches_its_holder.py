"""A batch issue reaches its holder the same way a single one does.

Bulk assignment accepted only a ``partner_id`` and stored it with the
partner's name — no email. "My assets" matches the holder by
``lower(assigned_to_email)`` (or by the holder's own partner rows), so an
asset issued to an organization member in a batch was invisible to the
person carrying it and unreachable by attestation, with no warning
anywhere. The single-issue path has stored the email since its holder
search learned the organization's own accounts; the batch path now takes
the same fields.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment.my_assets_service import get_my_active_assets
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def eq_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Batch Issue Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'equipment'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def eq_user(real_async_db_session: AsyncSession, eq_org: Organization) -> User:
    user = User(
        email=f'batch_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Batch Issue User',
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
        name='Cage B',
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
async def eq_item(
    real_async_db_session: AsyncSession,
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
) -> Item:
    item = Item(
        name='ThinkPad',
        organization_id=eq_org.id,
        storage_location_id=eq_storage_location.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    real_async_db_session.add(item)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(item)
    return item


async def _bulk_assign(
    client: AsyncClient,
    user: User,
    item: Item,
    data: dict[str, str],
) -> dict[str, Any]:
    response = await client.patch(
        '/api/v1/equipment/assets/bulk',
        headers=_auth(user),
        json={'item_ids': [str(item.id)], 'action': 'assign_to', 'data': data},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.mark.integration
@pytest.mark.asyncio
class TestABatchIssueReachesItsHolder:
    async def test_an_asset_issued_to_a_member_is_visible_in_my_assets(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        """The whole point of the fix: pick the person, and the asset shows
        up on their page — same as a single issue to the same person."""
        result = await _bulk_assign(
            real_async_client,
            eq_user,
            eq_item,
            {
                'assigned_to_name': 'Anna Kowalska',
                'assigned_to_email': 'Anna.Kowalska@Example.org',
            },
        )

        assert result['updated'] == 1, result['errors']
        active = await get_my_active_assets(
            real_async_db_session, eq_org.id, 'anna.kowalska@example.org'
        )
        assert [row['item_id'] for row in active] == [eq_item.id]

    async def test_a_partner_issue_still_carries_the_email_it_was_given(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        """The dialog sends the person it showed — for a partner pick that
        includes the partner's email, and the record stores it lowercased
        like the single checkout does."""
        from sqlalchemy import select

        from app.models.partner import Partner
        from app.modules.equipment.models import EquipmentAssignment

        partner = Partner(
            organization_id=eq_org.id,
            name='Kancelaria Nowak',
            type='COMPANY',
            email='Desk@example.org',
            created_by=eq_user.id,
        )
        real_async_db_session.add(partner)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(partner)

        result = await _bulk_assign(
            real_async_client,
            eq_user,
            eq_item,
            {
                'partner_id': str(partner.id),
                'assigned_to_name': 'Kancelaria Nowak',
                'assigned_to_email': 'Desk@Example.org',
            },
        )

        assert result['updated'] == 1, result['errors']
        row = (
            (
                await real_async_db_session.execute(
                    select(EquipmentAssignment).where(
                        EquipmentAssignment.item_id == eq_item.id
                    )
                )
            )
            .scalars()
            .one()
        )
        assert row.assigned_to_email == 'desk@example.org'
        assert row.assigned_to_name == 'Kancelaria Nowak'
        assert row.assignee_partner_id == partner.id
