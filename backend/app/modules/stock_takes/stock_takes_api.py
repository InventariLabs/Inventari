"""Public Cross-Module API for the stock_takes module.

Other modules read what is due from here instead of importing the schedule
and stock take models. Like the other ``*_api`` singletons it answers with an empty result
when nothing is scheduled.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StorageDTO, WorkItemDTO, WorkItemQueryDTO
from app.core.module_scope import get_claimed_context_tags
from app.core.module_sdk import join_location_path
from app.core.public_api import core_api

from .cycle_count_service import (
    counts_under_way_by_location,
    last_counted_by_location,
)
from .models import (
    CycleCountFrequency,
    CycleCountSchedule,
    StockTake,
    StockTakeStatus,
)

#: The module setting that turns on counting by age: every location holding
#: stock is due this many days after its last count. 0 (the default) is off.
COUNT_EVERY_DAYS = 'count_every_days'

#: How long after a count the next one is due, by schedule frequency.
_PERIOD: dict[CycleCountFrequency, timedelta] = {
    CycleCountFrequency.DAILY: timedelta(days=1),
    CycleCountFrequency.WEEKLY: timedelta(days=7),
    CycleCountFrequency.MONTHLY: timedelta(days=30),
    CycleCountFrequency.QUARTERLY: timedelta(days=91),
}


class StockTakesAPI:
    """Single public entry point for cross-module consumption of counts."""

    async def list_work_items_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        query: WorkItemQueryDTO,
    ) -> tuple[list[WorkItemDTO], int]:
        """Counts that are due, under way, or (when asked) finished lately.

        To do's provider for this module. A schedule's next count is due one
        period after the last run, or after the schedule was made if it has
        never run. The count a schedule generated is the stock take that names
        it: while that one is in progress the task is ``in_progress`` and opens
        it, and one completed at or after ``query.done_since`` is ``done``.
        Most overdue first; ``subject`` is the schedule's name.
        """
        schedules = (
            (
                await db.execute(
                    select(CycleCountSchedule).where(
                        CycleCountSchedule.organization_id == organization_id,
                        CycleCountSchedule.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        takes = (
            await db.execute(
                select(
                    StockTake.schedule_id,
                    StockTake.id,
                    StockTake.status,
                    StockTake.completed_at,
                ).where(
                    StockTake.organization_id == organization_id,
                    StockTake.schedule_id.in_([schedule.id for schedule in schedules]),
                    StockTake.deleted_at.is_(None),
                    StockTake.status.in_(
                        [StockTakeStatus.IN_PROGRESS, StockTakeStatus.COMPLETED]
                    ),
                )
            )
        ).all()
        under_way = {
            schedule_id: take_id
            for schedule_id, take_id, take_status, _ in takes
            if take_status == StockTakeStatus.IN_PROGRESS
        }
        finished = {
            schedule_id
            for schedule_id, _, take_status, completed_at in takes
            if take_status == StockTakeStatus.COMPLETED
            and query.done_since is not None
            and completed_at is not None
            and completed_at >= query.done_since
        }
        rows: list[WorkItemDTO] = []
        for schedule in schedules:
            since = schedule.last_run_at or schedule.created_at
            due_on = (since.astimezone(UTC) + _PERIOD[schedule.frequency]).date()
            state: Literal['todo', 'in_progress', 'done'] = 'todo'
            href: str | None = None
            if schedule.id in under_way:
                state = 'in_progress'
                href = f'/inventory/stock-takes/{under_way[schedule.id]}/counting'
            elif due_on > query.date_to:
                if schedule.id not in finished:
                    continue
                state = 'done'
            rows.append(
                WorkItemDTO(
                    kind='count',
                    source_kind='cycle_count',
                    source_id=schedule.id,
                    state=state,
                    # A run moves ``last_run_at`` to now, so ``due_on`` of a
                    # count under way or finished is the next period's day,
                    # not the day this one fell due.
                    due_date=due_on if state == 'todo' else None,
                    subject=schedule.name,
                    next_action=None if state == 'done' else 'count',
                    action_href=href,
                )
            )
        rows += await _due_location_counts(db, organization_id, query)
        # A row with no day goes after the dated ones, as in the shared order,
        # so it cannot crowd them out of the cut below.
        rows.sort(
            key=lambda row: (
                row.due_date is None,
                row.due_date or date.min,
                row.subject or '',
            )
        )
        return rows[: query.limit], len(rows)

    async def last_counted_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storages: list[StorageDTO],
    ) -> dict[UUID, datetime]:
        """When each of ``storages`` was last counted; never counted are absent.

        The same proof of a count the due-count tasks read — a closed count
        that left nothing at the location uncounted. Another module asks this
        to know whether a count it asked for has happened.
        """
        return await last_counted_by_location(db, organization_id, storages)


async def _due_location_counts(
    db: AsyncSession, organization_id: UUID, query: WorkItemQueryDTO
) -> list[WorkItemDTO]:
    """The locations that fall due under "count every N days".

    The setting is off by default. On, every location that holds stock is due
    once N whole days have passed since the last count that counted it, and a
    location never counted is due today; due dates are laid onto the reader's
    today (``query.date_to``), not onto a UTC calendar. A location under an open count is ``in_progress`` and opens
    it; one counted since ``query.done_since`` and not due again is ``done``.
    ``subject`` is the location's path and ``count`` the days since its last
    count (empty when it never was).
    """
    every = await core_api.settings.get_async(
        db, organization_id, 'stock_takes', COUNT_EVERY_DAYS, default=0
    )
    if not isinstance(every, int) or every <= 0:
        return []
    # Only the shelves that hold something, with the racks and zones above
    # them: the organization's other locations have nothing to count.
    storages = await core_api.locations.list_holding_stock_with_ancestors_async(
        db, organization_id, usage='internal'
    )
    holding = await core_api.locations.item_counts_by_location_async(
        db, organization_id, [storage.id for storage in storages]
    )
    # The organization's own policy, the one the general screens follow: a
    # location a vertical module owns (an equipment rack) is not offered for
    # counting unless the organization shows module data in its lists.
    settings = await core_api.organizations.get_settings_async(db, organization_id)
    hidden = (
        set()
        if (settings or {}).get('show_module_data') is True
        else get_claimed_context_tags()
    )
    last_counted = await last_counted_by_location(db, organization_id, storages)
    under_way = await counts_under_way_by_location(db, organization_id, storages)
    now = datetime.now(UTC)
    by_id = {storage.id: storage for storage in storages}
    rows: list[WorkItemDTO] = []
    for storage in storages:
        if (
            storage.usage != 'internal'
            or not holding.get(storage.id)
            or storage.context_tag in hidden
        ):
            continue
        counted_at = last_counted.get(storage.id)
        # Whole days elapsed, the count screen's own measure, laid onto the
        # reader's today: a UTC date would put a count made tonight east of
        # UTC on yesterday's page and make it due again at once.
        age = (now - counted_at) // timedelta(days=1) if counted_at else None
        due_on = query.date_to + timedelta(days=every - age if age is not None else 0)
        state: Literal['todo', 'in_progress', 'done'] = 'todo'
        href: str | None = f'/inventory/stock-takes/count?location={storage.id}'
        if storage.id in under_way:
            state = 'in_progress'
            href = f'/inventory/stock-takes/{under_way[storage.id]}/counting'
        elif due_on > query.date_to:
            if (
                query.done_since is None
                or counted_at is None
                or counted_at < query.done_since
            ):
                continue
            state = 'done'
            href = None
        rows.append(
            WorkItemDTO(
                kind='count',
                source_kind='location',
                source_id=storage.id,
                state=state,
                # A finished count's ``due_on`` is the next period's day, and
                # nothing falls due on a count that is done.
                due_date=due_on if state != 'done' else None,
                subject=_path(by_id, storage),
                count=Decimal(age) if age is not None else None,
                next_action=None if state == 'done' else 'count',
                action_href=href,
            )
        )
    return rows


def _path(by_id: dict[UUID, StorageDTO], storage: StorageDTO) -> str:
    """The location as a person finds it: "Main Warehouse › Shelf A"."""
    chain: list[str] = []
    cursor: StorageDTO | None = storage
    while cursor is not None and len(chain) < len(by_id):
        chain.append(cursor.name)
        cursor = by_id.get(cursor.parent_id) if cursor.parent_id else None
    return join_location_path(reversed(chain))


stock_takes_api = StockTakesAPI()
