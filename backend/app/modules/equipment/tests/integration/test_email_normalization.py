"""
Integration tests for assigned_to_email normalization.

The checkout stores the email lowercased, so "My assets" finds the same mailbox
whatever the casing it was typed in. Emails are case-insensitive by RFC 5321:
store them lowercase and compare case-insensitively.
"""

from collections.abc import Callable
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment.models import EquipmentAssignment
from app.modules.equipment.my_assets_service import (
    get_my_active_assets,
    get_my_assignment_history,
)
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def eq_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Email Norm Org',
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
        full_name='Email Norm User',
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
        category_id=eq_category.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    real_async_db_session.add(item)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(item)
    return item


@pytest.mark.integration
@pytest.mark.asyncio
class TestEmailNormalization:
    async def test_my_assets_does_not_invent_a_missing_status(
        self,
        real_async_db_session: AsyncSession,
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        eq_item.meta_data = {'equipment': {}}
        real_async_db_session.add(
            EquipmentAssignment(
                organization_id=eq_org.id,
                item_id=eq_item.id,
                assigned_to_name='Anna Kowalska',
                assigned_to_email='anna@example.org',
                checked_out_by=eq_user.id,
            )
        )
        await real_async_db_session.commit()
        assets = await get_my_active_assets(
            real_async_db_session, eq_org.id, 'anna@example.org'
        )
        assert len(assets) == 1
        assert assets[0]['equipment_status'] is None

    async def test_checkout_stores_email_lowercase(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        response = await real_async_client.post(
            '/api/v1/equipment/assignments',
            headers=_auth(eq_user),
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Anna Kowalska',
                'assigned_to_email': 'Anna.Kowalska@Example.org',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['assigned_to_email'] == 'anna.kowalska@example.org'

    async def test_my_assets_matches_legacy_mixed_case_email(
        self,
        real_async_db_session: AsyncSession,
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        from datetime import UTC, datetime

        # Legacy rows: stored verbatim with mixed case before.
        real_async_db_session.add(
            EquipmentAssignment(
                organization_id=eq_org.id,
                item_id=eq_item.id,
                assigned_to_name='Anna Kowalska',
                assigned_to_email='Anna.Kowalska@Example.org',
                checked_out_by=eq_user.id,
            )
        )
        real_async_db_session.add(
            EquipmentAssignment(
                organization_id=eq_org.id,
                item_id=eq_item.id,
                assigned_to_name='Anna Kowalska',
                assigned_to_email='Anna.Kowalska@Example.org',
                checked_out_by=eq_user.id,
                checked_in_at=datetime.now(UTC),
            )
        )
        await real_async_db_session.commit()

        active = await get_my_active_assets(
            real_async_db_session, eq_org.id, 'anna.kowalska@example.org'
        )
        assert len(active) == 1
        assert active[0]['item_id'] == eq_item.id

        history, _total = await get_my_assignment_history(
            real_async_db_session, eq_org.id, 'anna.kowalska@example.org'
        )
        assert len(history) == 1
        assert history[0]['item_id'] == eq_item.id

    async def test_my_assets_no_match_for_different_email(
        self,
        real_async_db_session: AsyncSession,
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
    ) -> None:
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

        active = await get_my_active_assets(
            real_async_db_session, eq_org.id, 'someone.else@example.org'
        )
        assert active == []

    @pytest.mark.parametrize('typed', [str.lower, str.upper])
    async def test_the_asset_history_names_the_holder_as_my_assets_does(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
        typed: Callable[[str], str],
    ) -> None:
        """A partner carrying the reader's address holds the asset for them.

        The row names no address: "My assets" counts it, and the asset's own
        history says the same, for this reader and for nobody else, however
        the partner's address is capitalised.
        """
        partner = Partner(
            organization_id=eq_org.id,
            name='Anna Kowalska',
            type='EMPLOYEE',
            email=typed(eq_user.email),
        )
        real_async_db_session.add(partner)
        await real_async_db_session.flush()
        real_async_db_session.add(
            EquipmentAssignment(
                organization_id=eq_org.id,
                item_id=eq_item.id,
                assignee_partner_id=partner.id,
                assigned_to_name='Anna Kowalska',
                checked_out_by=eq_user.id,
            )
        )
        other = User(
            email=f'other_{uuid4().hex[:8]}@test.com',
            hashed_password=get_password_hash('pass'),
            full_name='Somebody Else',
            organization_id=eq_org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(other)
        await real_async_db_session.commit()
        url = f'/api/v1/equipment/assignments/item/{eq_item.id}'

        mine = await get_my_active_assets(
            real_async_db_session, eq_org.id, eq_user.email
        )
        asked_by_holder = await real_async_client.get(url, headers=_auth(eq_user))
        asked_by_other = await real_async_client.get(url, headers=_auth(other))

        assert [a['item_id'] for a in mine] == [eq_item.id]
        assert asked_by_holder.json()['items'][0]['held_by_viewer'] is True
        assert asked_by_other.json()['items'][0]['held_by_viewer'] is False
