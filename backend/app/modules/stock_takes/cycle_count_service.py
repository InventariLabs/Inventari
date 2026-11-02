from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, StorageDTO
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from .models import (
    CycleCountFrequency,
    CycleCountSchedule,
    CycleCountScope,
    StockTake,
    StockTakeClosedLocation,
    StockTakeItem,
    StockTakeStatus,
)
from .stock_take_service import claim_location_for_counting


async def create_schedule(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    name: str,
    frequency: CycleCountFrequency = CycleCountFrequency.MONTHLY,
    scope: CycleCountScope = CycleCountScope.ALL,
    scope_filter: dict[str, Any] | None = None,
    sample_size: int | None = None,
    tolerance_percent: Decimal | None = None,
) -> CycleCountSchedule:
    schedule = CycleCountSchedule(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=name,
        frequency=frequency,
        scope=scope,
        scope_filter=scope_filter,
        sample_size=sample_size,
        tolerance_percent=tolerance_percent,
        is_active=True,
        created_by=user_id,
    )
    db.add(schedule)
    # A schedule is the rule future counts follow; the log keeps who set it
    # and what it says (the target is the count family it serves).
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.CYCLE_COUNT_SCHEDULE,
        target_id=schedule.id,
        snapshot={
            'name': name,
            'frequency': frequency.value
            if hasattr(frequency, 'value')
            else str(frequency),
            'scope': scope.value if hasattr(scope, 'value') else str(scope),
        },
    )
    await db.flush()
    await db.refresh(schedule)
    return schedule


async def update_schedule(
    db: AsyncSession,
    schedule_id: UUID,
    org_id: UUID,
    user_id: UUID | None = None,
    **kwargs: Any,
) -> CycleCountSchedule:
    result = await db.scalars(
        select(CycleCountSchedule)
        .where(
            CycleCountSchedule.id == schedule_id,
            CycleCountSchedule.organization_id == org_id,
        )
        .with_for_update()
    )
    schedule = result.first()
    if not schedule:
        raise ServiceRejectionError('cycle_count_schedule_not_found')

    # The router has already refused nulls on NOT NULL columns; a named null
    # that reaches this loop is a real clearing instruction for a nullable
    # column, and the blanket `is not None` filter here used to erase it.
    changed = sorted(kwargs)
    for key, value in kwargs.items():
        if hasattr(schedule, key):
            setattr(schedule, key, value)

    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.CYCLE_COUNT_SCHEDULE,
        target_id=schedule.id,
        snapshot={
            'name': schedule.name,
            'fields': changed,
        },
    )
    await db.flush()
    await db.refresh(schedule)
    return schedule


async def list_schedules(
    db: AsyncSession,
    org_id: UUID,
    active_only: bool = False,
) -> list[CycleCountSchedule]:
    query = select(CycleCountSchedule).where(
        CycleCountSchedule.organization_id == org_id,
    )
    if active_only:
        query = query.filter(CycleCountSchedule.is_active.is_(True))  # noqa: E712
    result = await db.scalars(
        query.order_by(CycleCountSchedule.created_at.desc(), CycleCountSchedule.id)
    )
    return list(result.all())


async def get_schedule(
    db: AsyncSession, schedule_id: UUID, org_id: UUID
) -> CycleCountSchedule | None:
    result = await db.scalars(
        select(CycleCountSchedule).where(
            CycleCountSchedule.id == schedule_id,
            CycleCountSchedule.organization_id == org_id,
        )
    )
    return result.first()


async def delete_schedule(
    db: AsyncSession, schedule_id: UUID, org_id: UUID, user_id: UUID | None = None
) -> bool:
    schedule = await get_schedule(db, schedule_id, org_id)
    if not schedule:
        return False
    # The row is about to be gone: the name travels in the snapshot.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.CYCLE_COUNT_SCHEDULE,
        target_id=schedule.id,
        snapshot={
            'name': schedule.name,
        },
    )
    await db.delete(schedule)
    await db.flush()
    return True


async def generate_cycle_count(
    db: AsyncSession,
    schedule_id: UUID,
    org_id: UUID,
    user_id: UUID,
) -> StockTake:
    schedule = await get_schedule(db, schedule_id, org_id)
    if not schedule:
        raise ServiceRejectionError('cycle_count_schedule_not_found')

    scope_filter = schedule.scope_filter or {}
    storage_location_id = scope_filter.get('storage_location_id')

    if not storage_location_id:
        raise ServiceRejectionError('cycle_count_scope_location_required')

    location_uuid = uuid.UUID(storage_location_id)
    # The same claim the manual path makes, and for the same reason: the
    # shelf, not the door. A nightly schedule firing on a shelf somebody is
    # already counting would post a second set of corrections against one
    # stock. This also resolves the location, so a missing one is refused
    # here rather than by a separate lookup.
    await claim_location_for_counting(db, org_id, location_uuid)
    cat_uuid: uuid.UUID | None = None
    if schedule.scope == CycleCountScope.CATEGORY:
        category_id = scope_filter.get('category_id')
        if category_id:
            cat_uuid = uuid.UUID(category_id)

    items = await core_api.items.list_async(
        db,
        org_id,
        storage_location_id=location_uuid,
        category_id=cat_uuid,
    )
    item_list = list(items)

    if schedule.sample_size and len(item_list) > schedule.sample_size:
        item_list = random.sample(item_list, schedule.sample_size)

    if not item_list:
        raise ServiceRejectionError('cycle_count_no_matching_items')

    stock_take = StockTake(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=user_id,
        storage_location_id=uuid.UUID(storage_location_id),
        schedule_id=schedule.id,
        name=f'Cycle Count: {schedule.name} — {datetime.now(UTC).strftime("%Y-%m-%d %H:%M")}',
        status=StockTakeStatus.IN_PROGRESS,
        blind_mode=True,
        tolerance_percent=schedule.tolerance_percent,
        require_full_count=False,
    )
    db.add(stock_take)
    await db.flush()

    for item in item_list:
        st_item = StockTakeItem(
            id=uuid.uuid4(),
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name or '',
            item_brand=getattr(item, 'brand', None),
            system_quantity=item.quantity,
            storage_location_id=item.location_id,
        )
        db.add(st_item)

    schedule.last_run_at = datetime.now(UTC)
    # The generated count is a stock take like the manual one: it claims a
    # location tree and freezes the records, so it journals too, naming the
    # schedule that fired.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take.id,
        snapshot={
            'name': stock_take.name,
            'storage_location_id': str(location_uuid),
            'items_count': len(item_list),
            'generated_from_schedule': schedule.name,
        },
    )
    await db.flush()
    await db.refresh(stock_take)
    return stock_take


def _nearest_covering[T](
    storages: list[StorageDTO], direct: dict[UUID, T]
) -> dict[UUID, T]:
    """What each location inherits from the counts that cover it.

    A count covers its location and every location below it. ``direct``
    holds what the counts say about the location they were opened on; each
    location takes its own, else its nearest ancestor's.
    """
    parent = {storage.id: storage.parent_id for storage in storages}
    covered: dict[UUID, T] = {}
    for storage in storages:
        cursor: UUID | None = storage.id
        seen: set[UUID] = set()
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            if cursor in direct:
                covered[storage.id] = direct[cursor]
                break
            cursor = parent.get(cursor)
    return covered


async def last_counted_by_location(
    db: AsyncSession, org_id: UUID, storages: list[StorageDTO]
) -> dict[UUID, datetime]:
    """When each of ``storages`` was last counted. Locations never counted are absent."""
    latest = await last_counted_everywhere(db, org_id)
    return {
        storage.id: latest[storage.id] for storage in storages if storage.id in latest
    }


async def last_counted_everywhere(
    db: AsyncSession, org_id: UUID
) -> dict[UUID, datetime]:
    """When every location the counts speak of was last counted, by location id.

    A location was counted by a closed count that counted every row it held
    there, or whose counter closed it as done (an empty shelf has no row to
    count, and closing it is the trace that somebody looked), or that was
    opened on it and left no row uncounted (a rack holding nothing of its
    own is still counted by a full count of it). Closing the
    count is not that proof by itself: a partial count can close with a shelf
    untouched, and a shelf added below the counted rack later was never in
    it. A count made from a schedule dates nothing — the schedule may sample
    a few records or one category, which says nothing about the rest.
    """
    closed = (
        StockTake.organization_id == org_id,
        StockTake.status == StockTakeStatus.COMPLETED,
        StockTake.deleted_at.is_(None),
        StockTake.completed_at.is_not(None),
        StockTake.schedule_id.is_(None),
    )
    fully_counted = (
        select(
            StockTakeItem.storage_location_id.label('location_id'),
            StockTake.completed_at.label('at'),
        )
        .join(StockTake, StockTake.id == StockTakeItem.stock_take_id)
        .where(*closed, StockTakeItem.storage_location_id.is_not(None))
        .group_by(StockTakeItem.storage_location_id, StockTake.id)
        .having(func.count() == func.count(StockTakeItem.counted_quantity))
    )
    closed_by_the_counter = (
        select(StockTakeClosedLocation.storage_location_id, StockTake.completed_at)
        .join(StockTake, StockTake.id == StockTakeClosedLocation.stock_take_id)
        .where(*closed, StockTakeClosedLocation.storage_location_id.is_not(None))
    )
    opened_on_and_finished = select(
        StockTake.storage_location_id, StockTake.completed_at
    ).where(
        *closed,
        ~exists().where(
            StockTakeItem.stock_take_id == StockTake.id,
            StockTakeItem.counted_quantity.is_(None),
        ),
    )
    counted = fully_counted.union_all(
        closed_by_the_counter, opened_on_and_finished
    ).subquery()
    rows = await db.execute(
        select(counted.c.location_id, func.max(counted.c.at)).group_by(
            counted.c.location_id
        )
    )
    return {row[0]: row[1] for row in rows.all()}


async def counts_under_way_by_location(
    db: AsyncSession, org_id: UUID, storages: list[StorageDTO]
) -> dict[UUID, UUID]:
    """The open count covering each of ``storages``, by stock take id.

    One count per tree at a time (``claim_location_for_counting``), so a
    location has at most one; the nearest wins should the rule ever bend.
    """
    return _nearest_covering(storages, await open_counts_by_root(db, org_id))


async def open_counts_by_root(db: AsyncSession, org_id: UUID) -> dict[UUID, UUID]:
    """Each open count's stock take id, by the location it was opened on."""
    rows = await db.execute(
        select(StockTake.storage_location_id, StockTake.id).where(
            StockTake.organization_id == org_id,
            StockTake.status == StockTakeStatus.IN_PROGRESS,
            StockTake.deleted_at.is_(None),
        )
    )
    return {row[0]: row[1] for row in rows.all()}
