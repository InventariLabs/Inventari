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

Every test holds the first change open until the second is seen waiting on
a lock, so the second has read its row before the first commits — the
interleaving the entries went wrong in — and cannot pass by starting late.
"""

from __future__ import annotations

import asyncio
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
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.schemas.partner import PartnerCreate, PartnerUpdate
from app.services import partner_service
from app.services.storage._queries import ensure_short_code_async

pytestmark = pytest.mark.integration

_Change = Callable[[AsyncSession], Awaitable[Any]]


async def _someone_is_waiting(db: AsyncSession) -> None:
    """Until another backend of this database waits on a lock.

    ``pg_stat_activity`` is read once per transaction and then kept, and this
    session's transaction stays open between the polls: a poll that ran before
    the second change reached its lock saw "nobody waiting" for good. The
    snapshot is dropped before each read.
    """
    for _ in range(500):
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
    raise AssertionError('the second change never waited for the first')


async def _one_after_the_other(
    db: AsyncSession, first: _Change, second: _Change
) -> tuple[Any, Any]:
    """*first* in a transaction held open until *second* waits on it."""

    async def _second() -> Any:
        async with AsyncSession(bind=db.bind, expire_on_commit=False) as session:
            result = await second(session)
            await session.commit()
            return result

    async with AsyncSession(bind=db.bind, expire_on_commit=False) as session:
        first_result = await first(session)
        waiting = asyncio.create_task(_second())
        await _someone_is_waiting(db)
        await session.commit()
        second_result = await waiting
    return first_result, second_result


async def _snapshots(db: AsyncSession, target_type: str, target_id: uuid.UUID):
    rows = await db.scalars(
        select(AuditLog.snapshot)
        .where(AuditLog.target_type == target_type, AuditLog.target_id == target_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id)
    )
    return list(rows.all())


async def test_two_edits_of_one_partner_journal_the_sequence_they_made(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
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

    await _one_after_the_other(db, _rename('Supplier A'), _rename('Supplier B'))

    _created, first, second = await _snapshots(db, AuditTargetType.PARTNER, partner_id)
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
