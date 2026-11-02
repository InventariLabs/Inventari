"""A label stuck on a product decides what a scan of it answers.

Binding a printed code to a product, freeing it again and deleting it each
change that answer, and none of them wrote a journal entry: a product that
"suddenly scanned as nothing" left nobody to ask. The entries are written in
``LabelService``, which the label routes and ``core_api.labels`` share.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog, AuditTargetType
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.label_service import LabelService

pytestmark = pytest.mark.integration


async def _entries(db: AsyncSession, label_id: uuid.UUID) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(
            AuditLog.target_type == AuditTargetType.LABEL,
            AuditLog.target_id == label_id,
        )
        .order_by(AuditLog.created_at.asc(), AuditLog.id)
    )
    return list(rows.all())


async def _label(db: AsyncSession, org: Organization, user: User, code: str):
    label = LabelPool(short_code=code, organization_id=org.id, created_by=user.id)
    db.add(label)
    await db.flush()
    return label


async def _product(db: AsyncSession, org: Organization, user: User) -> Item:
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Shelf')
    db.add(shelf)
    await db.flush()
    item = Item(
        organization_id=org.id,
        storage_location_id=shelf.id,
        name='Drill',
        quantity=1,
    )
    db.add(item)
    await db.flush()
    return item


async def test_binding_a_label_names_the_product_it_now_answers_for(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    label = await _label(db, async_test_household, async_test_user, 'LBL-B1')
    item = await _product(db, async_test_household, async_test_user)

    await LabelService.assign_to_existing_item_async(
        db, label, item.id, user_id=async_test_user.id
    )

    (entry,) = await _entries(db, label.id)
    assert entry.action == AuditAction.UPDATE
    assert entry.organization_id == async_test_household.id
    assert entry.user_id == async_test_user.id
    assert entry.snapshot == {
        'short_code': 'LBL-B1',
        'product_name': 'Drill',
        'before': {'item_id': None},
        'after': {'item_id': str(item.id)},
    }


async def test_a_new_label_frees_the_old_one_and_both_say_so(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    item = await _product(db, async_test_household, async_test_user)
    old = await _label(db, async_test_household, async_test_user, 'LBL-OLD')
    new = await _label(db, async_test_household, async_test_user, 'LBL-NEW')
    await LabelService.assign_to_existing_item_async(
        db, old, item.id, user_id=async_test_user.id
    )

    await LabelService.assign_to_existing_item_async(
        db, new, item.id, user_id=async_test_user.id
    )

    _bound, freed = await _entries(db, old.id)
    assert freed.snapshot == {
        'short_code': 'LBL-OLD',
        'product_name': 'Drill',
        'before': {'item_id': str(item.id)},
        'after': {'item_id': None},
    }
    (bound,) = await _entries(db, new.id)
    assert bound.snapshot['after'] == {'item_id': str(item.id)}


async def test_freeing_a_label_says_which_product_it_left(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    label = await _label(db, async_test_household, async_test_user, 'LBL-U1')
    item = await _product(db, async_test_household, async_test_user)
    await LabelService.assign_to_existing_item_async(
        db, label, item.id, user_id=async_test_user.id
    )

    await LabelService.unassign_label_async(db, label, user_id=async_test_user.id)

    _bound, freed = await _entries(db, label.id)
    assert freed.action == AuditAction.UPDATE
    assert freed.snapshot == {
        'short_code': 'LBL-U1',
        'product_name': 'Drill',
        'before': {'item_id': str(item.id)},
        'after': {'item_id': None},
    }


async def test_freeing_a_label_that_is_free_writes_nothing(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    label = await _label(db, async_test_household, async_test_user, 'LBL-U2')

    await LabelService.unassign_label_async(db, label, user_id=async_test_user.id)

    assert await _entries(db, label.id) == []


async def test_deleting_a_label_keeps_its_code_in_the_journal(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    label = await _label(db, async_test_household, async_test_user, 'LBL-D1')
    label_id = label.id

    await LabelService.delete_label_async(db, label, user_id=async_test_user.id)

    (entry,) = await _entries(db, label_id)
    assert entry.action == AuditAction.HARD_DELETE
    assert entry.user_id == async_test_user.id
    assert entry.snapshot == {'short_code': 'LBL-D1', 'description': None}
