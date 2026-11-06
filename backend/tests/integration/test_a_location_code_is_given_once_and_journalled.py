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
import sys
import time
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

# Only for a change stuck on something else: nothing here takes this long, and
# no test passes or fails on how close it comes.
_NEVER_ARRIVES_AFTER = 120.0


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


async def _backend_pid(session: AsyncSession) -> int:
    """The server process behind *session*, which keeps it until it ends."""
    return int(await session.scalar(text('SELECT pg_backend_pid()')))


async def _renumber_waits_for_the_create(
    db: AsyncSession, renumber: asyncio.Task[None], renumber_pid: int, create_pid: int
) -> None:
    """Until the create's backend holds up the renumber's.

    The create holds its transaction open until then, so the renumber is
    known to have reached the point where it would collide — on the advisory
    lock with the fix, on the unique index without it — before the create
    commits. Without the wait the renumber might simply start after the
    commit and pass for the wrong reason.

    The answer comes from the lock table, by the two backends' numbers, which
    the caller reads before the renumber starts. Counting waiters in
    ``pg_stat_activity`` took any backend waiting on any lock for the
    renumber.

    A renumber that raised is answered by its own exception. One that finished
    without waiting read the codes before the create committed, so the codes
    the test goes on to read say what that did.
    """
    deadline = time.monotonic() + _NEVER_ARRIVES_AFTER
    while not renumber.done():
        if await db.scalar(
            text('SELECT :create = ANY(pg_blocking_pids(:renumber))'),
            {'create': create_pid, 'renumber': renumber_pid},
        ):
            return
        if time.monotonic() > deadline:
            raise AssertionError('the renumber never reached the lock')
        await asyncio.sleep(0.01)
    renumber.result()


async def test_a_renumber_that_fails_reports_its_own_failure(
    real_async_db_session: AsyncSession,
) -> None:
    async def _breaks() -> None:
        raise LookupError('the renumber broke')

    with pytest.raises(LookupError, match='the renumber broke'):
        await _renumber_waits_for_the_create(
            real_async_db_session, asyncio.create_task(_breaks()), 0, 0
        )


async def test_a_stranger_waiting_on_a_lock_is_not_the_renumber(
    real_async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = real_async_db_session
    take = text('SELECT pg_advisory_xact_lock(7)')
    monkeypatch.setattr(sys.modules[__name__], '_NEVER_ARRIVES_AFTER', 0.3)

    async with (
        AsyncSession(bind=db.bind) as holder,
        AsyncSession(bind=db.bind) as stranger,
        AsyncSession(bind=db.bind) as renumbering,
    ):
        holder_pid = await _backend_pid(holder)
        renumber_pid = await _backend_pid(renumbering)
        await holder.execute(take)
        queued = asyncio.create_task(stranger.execute(take))
        # The renumber, still idle, is not held up by the create just because
        # the stranger is.
        renumber = asyncio.create_task(asyncio.sleep(30))
        try:
            with pytest.raises(AssertionError, match='never reached the lock'):
                await _renumber_waits_for_the_create(
                    db, renumber, renumber_pid, holder_pid
                )
        finally:
            renumber.cancel()
            await holder.rollback()
            await queued


async def _renumber(
    session: AsyncSession, org_id: UUID, user_id: UUID, warehouse_id: UUID
) -> None:
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
    async with (
        AsyncSession(bind=engine, expire_on_commit=False) as create,
        AsyncSession(bind=engine, expire_on_commit=False) as renumbering,
    ):
        # Both backends are known before either statement of the race runs.
        create_pid = await _backend_pid(create)
        renumber_pid = await _backend_pid(renumbering)
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

        renumber = asyncio.create_task(
            _renumber(renumbering, org_id, user_id, warehouse_id)
        )
        try:
            await _renumber_waits_for_the_create(db, renumber, renumber_pid, create_pid)
        except BaseException:
            # Not left queueing behind a create that is about to roll back.
            await create.rollback()
            await asyncio.gather(renumber, return_exceptions=True)
            raise
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
