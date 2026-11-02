"""Two places created in the same moment both get a code of their own.

The next shelf code is read from the siblings that exist, so two requests
that read before either one committed both computed the same letter and the
second insert died on ``uq_storage_locations_org_short_code`` — a 500 for a
request that had done nothing wrong. Every caller that numbers a new place
goes through ``code_for_new_location_async``, which now serialises per
organization until the transaction ends.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.storage._codes import code_for_new_location_async

pytestmark = pytest.mark.integration


async def _create(
    engine, org_id: UUID, user_id: UUID, parent_id: UUID, name: str
) -> str:
    """What the create path does: draw the code, insert, then end the request."""
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        code = await code_for_new_location_async(session, org_id, parent_id)
        session.add(
            StorageLocation(
                organization_id=org_id,
                created_by=user_id,
                parent_id=parent_id,
                name=name,
                short_code=code,
            )
        )
        await session.flush()
        await session.commit()
        return code


@pytest.mark.asyncio
async def test_two_zones_created_at_once_take_different_letters(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    org = async_test_household
    org.active_profile_id = 'equipment_wms'
    warehouse = StorageLocation(
        organization_id=org.id,
        created_by=async_test_user.id,
        name='Main Warehouse',
        short_code='WH-1',
    )
    real_async_db_session.add(warehouse)
    await real_async_db_session.commit()

    engine = real_async_db_session.bind
    user_id = async_test_user.id
    codes = await asyncio.gather(
        _create(engine, org.id, user_id, warehouse.id, 'Zone North'),
        _create(engine, org.id, user_id, warehouse.id, 'Zone South'),
    )

    assert sorted(codes) == ['A', 'B']
    stored = await real_async_db_session.scalars(
        select(StorageLocation.short_code).where(
            StorageLocation.parent_id == warehouse.id
        )
    )
    assert sorted(stored.all()) == ['A', 'B']
