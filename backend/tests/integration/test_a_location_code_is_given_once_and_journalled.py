"""A location's code is what a worker scans to name the shelf.

Two things were wrong with how a code was given:

- "Generate code" for a location that had none set the column and wrote
  nothing into the journal, while renumbering the same location wrote the
  change of code with its before and after. The same fact read differently
  depending on the button.
- Renumbering a branch read the codes in use without the per-organization
  lock a new location takes before it draws its own. A location created
  while the renumber ran could draw the very code the renumber was about to
  give, and one of the two transactions ended on
  ``uq_storage_locations_org_short_code`` — a 500 for a request that had done
  nothing wrong. The renumber now waits for the lock like a create does.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog, AuditTargetType
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.storage._codes import (
    code_for_new_location_async,
    number_branch_async,
)
from app.services.storage._queries import ensure_short_code_async

pytestmark = pytest.mark.integration


async def _warehouse(
    db: AsyncSession, org: Organization, user: User
) -> StorageLocation:
    org.active_profile_id = 'equipment_wms'
    warehouse = StorageLocation(
        organization_id=org.id,
        created_by=user.id,
        name='Main Warehouse',
        short_code='WH-1',
    )
    db.add(warehouse)
    await db.commit()
    return warehouse


async def test_generating_a_missing_code_is_journalled_like_a_renumber(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    warehouse = await _warehouse(db, async_test_household, async_test_user)
    zone = StorageLocation(
        organization_id=async_test_household.id,
        created_by=async_test_user.id,
        parent_id=warehouse.id,
        name='Zone North',
    )
    db.add(zone)
    await db.flush()

    await ensure_short_code_async(db, zone, user_id=async_test_user.id)

    (entry,) = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.target_type == AuditTargetType.STORAGE,
                AuditLog.target_id == zone.id,
            )
        )
    ).all()
    assert entry.action == AuditAction.UPDATE
    assert entry.user_id == async_test_user.id
    assert entry.snapshot == {
        'name': 'Zone North',
        'before': {'short_code': None},
        'after': {'short_code': zone.short_code},
    }


async def test_a_location_that_has_a_code_keeps_it_and_writes_nothing(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    warehouse = await _warehouse(db, async_test_household, async_test_user)

    await ensure_short_code_async(db, warehouse, user_id=async_test_user.id)

    assert warehouse.short_code == 'WH-1'
    entries = await db.scalars(
        select(AuditLog).where(AuditLog.target_id == warehouse.id)
    )
    assert entries.all() == []


async def _someone_is_waiting(db: AsyncSession) -> None:
    """Until another backend of this database waits on a lock.

    The create holds its transaction open until then, so the renumber is
    known to have reached the point where it would collide — on the advisory
    lock with the fix, on the unique index without it — before the create
    commits. Without the wait the renumber might simply start after the
    commit and pass for the wrong reason.
    """
    for _ in range(500):
        # pg_stat_activity is a snapshot per transaction and this session's
        # stays open: drop it, or the loop rereads its first poll forever.
        await db.execute(text('SELECT pg_stat_clear_snapshot()'))
        waiting = await db.scalar(
            text(
                'SELECT count(*) FROM pg_stat_activity '
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )
        if waiting:
            return
        await asyncio.sleep(0.01)
    raise AssertionError('the renumber never reached the lock')


async def _renumber(engine, org_id: UUID, user_id: UUID, warehouse_id: UUID) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        await number_branch_async(session, org_id, user_id, warehouse_id, renumber=True)
        await session.commit()


async def test_a_renumber_and_a_create_at_once_both_succeed(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org_id, user_id = async_test_household.id, async_test_user.id
    warehouse = await _warehouse(db, async_test_household, async_test_user)
    warehouse_id = warehouse.id
    # A zone from before templates: the renumber gives it the first letter.
    db.add(
        StorageLocation(
            organization_id=org_id,
            created_by=user_id,
            parent_id=warehouse_id,
            name='Old Zone',
            short_code='LOC-OLD1',
        )
    )
    await db.commit()

    engine = db.bind
    async with AsyncSession(bind=engine, expire_on_commit=False) as create:
        # The create draws the first letter too — the old zone carries no
        # template code — and holds it until it commits.
        code = await code_for_new_location_async(create, org_id, warehouse_id)
        assert code == 'A'
        create.add(
            StorageLocation(
                organization_id=org_id,
                created_by=user_id,
                parent_id=warehouse_id,
                name='New Zone',
                short_code=code,
            )
        )
        await create.flush()

        renumber = asyncio.create_task(_renumber(engine, org_id, user_id, warehouse_id))
        await _someone_is_waiting(db)
        await create.commit()
        await renumber

    db.expire_all()
    codes = dict(
        (
            await db.execute(
                select(StorageLocation.name, StorageLocation.short_code).where(
                    StorageLocation.parent_id == warehouse_id
                )
            )
        ).all()
    )
    assert codes == {'New Zone': 'A', 'Old Zone': 'B'}
