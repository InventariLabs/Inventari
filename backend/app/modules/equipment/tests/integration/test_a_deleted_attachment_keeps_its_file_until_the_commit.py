"""Deleting an attachment removes its file only once the row is gone for good.

The service used to delete the stored file inside the request, ahead of the
commit. A commit that then failed left the row in place and the file gone, so
the asset's attachment list lost a document it still named. The row goes in
the caller's transaction now; the file is removed afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment import attachment_service
from app.modules.equipment.models import EquipmentAttachment


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_rollback_after_the_delete_keeps_both_the_row_and_the_file(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(
        name=f'Attachment Org {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'equipment'],
    )
    db.add(org)
    await db.commit()
    user = User(
        email=f'attach_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password='x',
        full_name='Attach User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    storage_type = StorageType(
        name='IT Storage', type_code='IT_STORAGE', behavior_mode='NONE'
    )
    db.add_all([user, storage_type])
    await db.commit()
    location = StorageLocation(
        organization_id=org.id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name='Cage C',
    )
    db.add(location)
    await db.commit()
    item = Item(
        name='Printer',
        organization_id=org.id,
        storage_location_id=location.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db.add(item)
    await db.commit()
    org_id, user_id, item_id = org.id, user.id, item.id

    uploaded = await attachment_service.upload_attachment(
        db,
        org_id,
        item_id,
        user_id,
        b'%PDF-1.4 test',
        'a.pdf',
        'application/pdf',
        'INVOICE',
    )
    await db.commit()
    stored = await db.scalar(
        select(EquipmentAttachment.file_path).where(
            EquipmentAttachment.id == uploaded.id
        )
    )
    assert stored is not None

    returned = await attachment_service.delete_attachment(
        db, org_id, uploaded.id, user_id
    )
    await db.rollback()

    assert returned == stored
    assert await db.scalar(
        select(EquipmentAttachment.id).where(EquipmentAttachment.id == uploaded.id)
    )
    assert await core_api.file_storage.exists_for_org_async(org_id, 'equipment', stored)

    await attachment_service.discard_stored_file(org_id, stored)
    assert not await core_api.file_storage.exists_for_org_async(
        org_id, 'equipment', stored
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_papers_filed_and_removed_leave_the_asset_a_journal_entry(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(
        name=f'Attachment Journal Org {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'equipment'],
    )
    db.add(org)
    await db.commit()
    user = User(
        email=f'attach_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password='x',
        full_name='Attach User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    storage_type = StorageType(
        name='IT Storage', type_code='IT_STORAGE', behavior_mode='NONE'
    )
    db.add_all([user, storage_type])
    await db.commit()
    location = StorageLocation(
        organization_id=org.id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name='Cage D',
    )
    db.add(location)
    await db.commit()
    item = Item(
        name='Scanner',
        organization_id=org.id,
        storage_location_id=location.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db.add(item)
    await db.commit()
    org_id, user_id, item_id = org.id, user.id, item.id

    uploaded = await attachment_service.upload_attachment(
        db,
        org_id,
        item_id,
        user_id,
        b'%PDF-1.4 test',
        'warranty.pdf',
        'application/pdf',
        'WARRANTY',
    )
    path = await attachment_service.delete_attachment(db, org_id, uploaded.id, user_id)

    rows = (
        await db.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'equipment_asset',
                AuditLog.target_id == item_id,
            )
            .order_by(AuditLog.created_at)
        )
    ).all()
    snapshots = [r.snapshot or {} for r in rows]
    assert [s['before'] for s in snapshots] == [
        {'attachment': None},
        {'attachment': 'warranty.pdf'},
    ]
    assert [s['after'] for s in snapshots] == [
        {'attachment': 'warranty.pdf'},
        {'attachment': None},
    ]
    assert {s['name'] for s in snapshots} == {'Scanner'}
    assert {r.user_id for r in rows} == {user_id}

    await attachment_service.discard_stored_file(org_id, path)
