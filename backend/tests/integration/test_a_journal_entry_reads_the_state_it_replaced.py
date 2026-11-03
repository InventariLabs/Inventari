"""A journal entry says what a change replaced, and two changes can race.

Each write that journals a ``before`` read it from the row as the request
first loaded it, then waited — for the row's lock at the flush, or for the
organization's code lock — while another request changed the same row and
committed. The entry written after the wait then described a state that had
already gone: two edits of one supplier read "Review supplier → A" and
"Review supplier → B" when the supplier went Review → A → B, and two
requests to code one location both wrote "— → LOC-…", the second over the
code the first had just given. Each write now locks the row before it reads
what it journals, so the second request reads what the first left.

Every test holds the first change open until it is seen holding up the
second, or the second has finished, so the second has read its row before the
first commits — the interleaving the entries went wrong in — and cannot pass
by starting late.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.audit_log import AuditLog, AuditTargetType
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.schemas.partner import PartnerCreate, PartnerUpdate
from app.services import partner_service
from app.services.storage._queries import ensure_short_code_async

pytestmark = pytest.mark.integration

_Change = Callable[[AsyncSession], Awaitable[Any]]
_Rename = Callable[[str], _Change]

# Only for a change stuck on something else: nothing here takes this long, and
# no test passes or fails on how close it comes.
_NEVER_ARRIVES_AFTER = 30.0


async def _backend_pid(session: AsyncSession) -> int:
    """The server process behind *session*, which keeps it until it ends."""
    return int(await session.scalar(text('SELECT pg_backend_pid()')))


async def _held_up_or_finished(
    db: AsyncSession, second: asyncio.Task[Any], second_pid: int, first_pid: int
) -> None:
    """Until the first change's backend holds up the second's, or it has finished.

    The answer comes from the lock table, which is read as it stands, by the
    two backends' numbers. Counting waiters in ``pg_stat_activity`` read a
    snapshot the transaction kept, and took any backend waiting on any lock
    for the second change.

    A second change that finished without waiting read its rows before the
    first committed, so the journal the test goes on to read says what that
    did. One that raised is answered by its own exception.
    """
    deadline = time.monotonic() + _NEVER_ARRIVES_AFTER
    while not second.done():
        if await db.scalar(
            text('SELECT :first = ANY(pg_blocking_pids(:second))'),
            {'first': first_pid, 'second': second_pid},
        ):
            return
        if time.monotonic() > deadline:
            raise AssertionError('the second change never reached the first one')
        await asyncio.sleep(0.01)


async def _one_after_the_other(
    db: AsyncSession, first: _Change, second: _Change
) -> tuple[Any, Any]:
    """*first* in a transaction held open until it holds up *second*.

    Both connections are open before either change starts, so the backend to
    watch is known however late the event loop gets round to the second.
    """

    async def _second() -> Any:
        result = await second(second_session)
        await second_session.commit()
        return result

    async with (
        AsyncSession(bind=db.bind, expire_on_commit=False) as first_session,
        AsyncSession(bind=db.bind, expire_on_commit=False) as second_session,
    ):
        first_pid = await _backend_pid(first_session)
        second_pid = await _backend_pid(second_session)
        first_result = await first(first_session)
        racing = asyncio.create_task(_second())
        try:
            await _held_up_or_finished(db, racing, second_pid, first_pid)
            await first_session.commit()
            return first_result, await racing
        finally:
            # Not left running on a session that is about to close.
            racing.cancel()
            await asyncio.wait({racing})


@pytest.fixture
async def _review_supplier(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> _Rename:
    """A committed partner, and the change that renames it."""
    db = real_async_db_session
    org_id, user_id = async_test_household.id, async_test_user.id
    partner = await partner_service.create_async(
        db,
        org_id,
        PartnerCreate(name='Review supplier', type='SUPPLIER', code='RVW'),
        user_id,
    )
    partner_id = partner.id
    await db.commit()

    def _rename(name: str) -> _Change:
        return lambda session: partner_service.update_async(
            session, org_id, partner_id, PartnerUpdate(name=name), user_id=user_id
        )

    return _rename


async def _late(session: AsyncSession, change: _Change) -> str:
    """*change*, begun long after the first was started; the name it found."""
    await asyncio.sleep(0.2)
    found = await session.scalar(select(Partner.name).where(Partner.code == 'RVW'))
    await change(session)
    return found


async def test_a_second_change_that_starts_late_is_still_waited_for(
    real_async_db_session: AsyncSession, _review_supplier: _Rename
) -> None:
    rename = _review_supplier
    _first, found = await _one_after_the_other(
        real_async_db_session,
        rename('Supplier A'),
        lambda session: _late(session, rename('Supplier B')),
    )

    assert found == 'Review supplier'


async def _queued_on_a_lock(db: AsyncSession, pid: int) -> None:
    deadline = time.monotonic() + _NEVER_ARRIVES_AFTER
    while not await db.scalar(
        text('SELECT cardinality(pg_blocking_pids(:pid)) > 0'), {'pid': pid}
    ):
        assert time.monotonic() < deadline, 'the stranger never queued'
        await asyncio.sleep(0.01)


async def test_a_stranger_waiting_on_a_lock_is_not_the_second_change(
    real_async_db_session: AsyncSession, _review_supplier: _Rename
) -> None:
    db = real_async_db_session
    rename = _review_supplier
    take = text('SELECT pg_advisory_xact_lock(7)')

    async with (
        AsyncSession(bind=db.bind) as holder,
        AsyncSession(bind=db.bind) as stranger,
    ):
        stranger_pid = await _backend_pid(stranger)
        await holder.execute(take)
        queued = asyncio.create_task(stranger.execute(take))
        try:
            await _queued_on_a_lock(db, stranger_pid)
            _first, found = await _one_after_the_other(
                db,
                rename('Supplier A'),
                lambda session: _late(session, rename('Supplier B')),
            )
        finally:
            await holder.rollback()
            await queued

    # The first change was held for the second, not let go by the stranger.
    assert found == 'Review supplier'


async def test_a_second_change_stuck_on_another_lock_is_reported_and_stopped(
    real_async_db_session: AsyncSession,
    _review_supplier: _Rename,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = real_async_db_session
    rename = _review_supplier
    take = text('SELECT pg_advisory_xact_lock(7)')
    monkeypatch.setitem(globals(), '_NEVER_ARRIVES_AFTER', 0.3)

    async with AsyncSession(bind=db.bind) as holder:
        await holder.execute(take)
        with pytest.raises(AssertionError, match='never reached the first'):
            await _one_after_the_other(
                db, rename('Supplier A'), lambda session: session.execute(take)
            )
        # Stopped, not left queueing behind this holder for the next test.
        await db.execute(text('SELECT pg_stat_clear_snapshot()'))
        assert not await db.scalar(
            text(
                'SELECT count(*) FROM pg_stat_activity '
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )


async def test_a_second_change_that_fails_reports_its_own_failure(
    real_async_db_session: AsyncSession, _review_supplier: _Rename
) -> None:
    rename = _review_supplier

    async def _breaks(_session: AsyncSession) -> None:
        raise LookupError('the second change broke')

    with pytest.raises(LookupError, match='the second change broke'):
        await _one_after_the_other(real_async_db_session, rename('Supplier A'), _breaks)


async def _snapshots(db: AsyncSession, target_type: str, target_id: uuid.UUID):
    rows = await db.scalars(
        select(AuditLog.snapshot)
        .where(AuditLog.target_type == target_type, AuditLog.target_id == target_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id)
    )
    return list(rows.all())


async def test_two_edits_of_one_partner_journal_the_sequence_they_made(
    real_async_db_session: AsyncSession, _review_supplier: _Rename
) -> None:
    db = real_async_db_session
    rename = _review_supplier

    partner, _second = await _one_after_the_other(
        db, rename('Supplier A'), rename('Supplier B')
    )

    _created, first, second = await _snapshots(db, AuditTargetType.PARTNER, partner.id)
    assert (first['before'], first['after']) == (
        {'name': 'Review supplier'},
        {'name': 'Supplier A'},
    )
    assert (second['before'], second['after']) == (
        {'name': 'Supplier A'},
        {'name': 'Supplier B'},
    )


async def test_two_requests_to_code_one_location_give_it_one_code(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org_id, user_id = async_test_household.id, async_test_user.id
    location = StorageLocation(
        organization_id=org_id, created_by=user_id, name='Back room'
    )
    db.add(location)
    await db.flush()
    location_id = location.id
    await db.commit()

    async def _code(session: AsyncSession) -> str | None:
        loaded = await session.get(StorageLocation, location_id)
        assert loaded is not None
        coded = await ensure_short_code_async(session, loaded, user_id=user_id)
        return coded.short_code

    first, second = await _one_after_the_other(db, _code, _code)

    # The second request answers with the code the first gave rather than
    # drawing another over it, so the label a worker printed from the first
    # answer still scans.
    assert first is not None
    assert second == first
    (entry,) = await _snapshots(db, AuditTargetType.STORAGE, location_id)
    assert entry['after'] == {'short_code': first}


async def test_a_release_racing_a_hold_journals_the_hold_it_released(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    flour = ProductTemplate(name='Rye flour', organization_id=org_id)
    db.add(flour)
    await db.flush()
    lot = StockLot(organization_id=org_id, product_template_id=flour.id, name='L-1')
    db.add(lot)
    await db.flush()
    lot_id = lot.id
    await db.commit()

    await _one_after_the_other(
        db,
        lambda session: core_api.stock.quarantine_lot_async(
            session, org_id, lot_id, reason='Lab sample pending'
        ),
        lambda session: core_api.stock.release_lot_async(session, org_id, lot_id),
    )

    # Without the lock the release read the batch as still active, found
    # nothing to release, and the journal ended on a hold that was over.
    held, released = await _snapshots(db, AuditTargetType.STOCK_LOT, lot_id)
    assert (held['previous_status'], held['status']) == (
        LotStatus.ACTIVE,
        LotStatus.QUARANTINED,
    )
    assert (released['previous_status'], released['status']) == (
        LotStatus.QUARANTINED,
        LotStatus.ACTIVE,
    )


async def test_freeing_a_label_twice_at_once_journals_one_freeing(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org_id, user_id = async_test_household.id, async_test_user.id
    shelf = StorageLocation(organization_id=org_id, created_by=user_id, name='Shelf')
    db.add(shelf)
    await db.flush()
    item = Item(
        organization_id=org_id,
        storage_location_id=shelf.id,
        name='Drill',
        quantity=1,
        label_code='LBL-R1',
    )
    db.add(item)
    await db.flush()
    label = LabelPool(
        short_code='LBL-R1',
        organization_id=org_id,
        created_by=user_id,
        item_id=item.id,
        is_assigned=True,
    )
    db.add(label)
    await db.flush()
    label_id, item_id = label.id, item.id
    await db.commit()

    def _free(session: AsyncSession):
        return core_api.labels.unassign_async(
            session, 'LBL-R1', org_id, user_id=user_id
        )

    await _one_after_the_other(db, _free, _free)

    (entry,) = await _snapshots(db, AuditTargetType.LABEL, label_id)
    assert entry['before'] == {'item_id': str(item_id)}
    assert entry['after'] == {'item_id': None}
