"""Archiving an asset is not durable until the caller commits.

The maintenance service used to commit inside the archive, so a request
that failed after it had already taken the asset out of the register. The
caller owns the commit now: a rollback after the call leaves the asset
where it was.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment._maintenance_service import archive_item


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_rollback_after_the_archive_keeps_the_asset_in_the_register(
    real_async_db_session: AsyncSession,
) -> None:
    org = Organization(
        name=f'Archive Org {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'equipment'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    user = User(
        email=f'archive_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password='x',
        full_name='Archive User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    storage_type = StorageType(
        name='IT Storage', type_code='IT_STORAGE', behavior_mode='NONE'
    )
    real_async_db_session.add_all([user, storage_type])
    await real_async_db_session.commit()
    location = StorageLocation(
        organization_id=org.id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name='Cage B',
    )
    real_async_db_session.add(location)
    await real_async_db_session.commit()
    item = Item(
        name='ThinkPad',
        organization_id=org.id,
        storage_location_id=location.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    real_async_db_session.add(item)
    await real_async_db_session.commit()
    org_id, user_id, item_id = org.id, user.id, item.id

    await archive_item(
        real_async_db_session,
        org_id,
        item_id,
        UserContextDTO(id=user_id, organization_id=org_id, role='admin'),
    )
    await real_async_db_session.rollback()

    archived = await real_async_db_session.scalar(
        select(Item.is_deleted).where(Item.id == item_id)
    )
    assert archived is False
