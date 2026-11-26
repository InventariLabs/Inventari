"""An organization has its virtual places from the moment it exists.

Consumed, Inventory Loss and Production are where stock that is used up, lost
or being made goes. A door that empties a record locks that place's group
together with the shelf's, which it can only do for a place that is there:
one made halfway through an operation is locked after the shelf, and two
operations that both make it answer a name collision. So both ways an
organization is founded leave the three places behind them, whether or not
anybody ever walks through the onboarding.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from app.schemas.organization import OrganizationCreate
from app.schemas.user import UserCreate
from app.services._org_writes import create_organization
from app.services.auth_service import AuthService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _virtual_places(db: AsyncSession, organization_id: uuid.UUID) -> list[str]:
    usages = await db.scalars(
        select(StorageLocation.usage).where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.usage != LocationUsage.INTERNAL,
        )
    )
    return sorted(usages.all())


_THE_THREE = sorted(
    [LocationUsage.CUSTOMER, LocationUsage.INVENTORY, LocationUsage.PRODUCTION]
)


async def test_a_self_registered_organization_has_them(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session

    user = await AuthService.register_user_async(
        db,
        UserCreate(
            email=f'newcomer_{uuid.uuid4().hex[:8]}@test.com',
            full_name='Newcomer',
            password='Str0ng!passphrase',
        ),
    )

    assert user.organization_id is not None
    assert await _virtual_places(db, user.organization_id) == _THE_THREE


async def test_an_organization_somebody_creates_has_them(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    creator = User(
        email=f'founder_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password='!',
        full_name='Founder',
        role='user',
    )
    db.add(creator)
    await db.flush()

    organization = await create_organization(
        db, OrganizationCreate(name='Founded'), creator
    )

    assert await _virtual_places(db, organization.id) == _THE_THREE
