"""Inventory period service — month-end closure and workflow guards.

Period closure blocks document modifications (confirm, complete, cancel, update)
for any document dated within the closed period.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from babel.dates import format_date
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock, paginate_async
from app.core.exceptions import PeriodClosedError, ServiceRejectionError
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from .models import InventoryPeriod

# Re-export for intra-module relative imports (router.py, _document_workflow_crud.py).
# The canonical definition lives in app.core.exceptions so every module can
# import it without a cross-module dependency on the warehouse module.
__all__ = [
    'PeriodClosedError',
    'check_period_not_closed_async',
    'check_stock_change_period_open_async',
    'is_period_closed',
]


async def _get_user_name(
    db: AsyncSession, org_id: UUID, user_id: UUID | None
) -> str | None:
    if user_id is None:
        return None
    user = await core_api.users.get_async(db, org_id, user_id)
    return user.full_name if user else None


def period_is_closed(period: InventoryPeriod) -> bool:
    """Whether the month is locked right now, from which act came last.

    Both stamps are kept, so neither can be read alone. Reopening used to
    NULL ``closed_at`` and ``closed_by``, which meant undoing a closure also
    erased the evidence that it had happened and who was responsible — the
    one act in the whole system where that evidence matters most. Now the
    row holds both dates and the later one wins.
    """
    if period.closed_at is None:
        return False
    return period.reopened_at is None or period.closed_at > period.reopened_at


def period_label(year: int, month: int) -> str:
    """A month as the period screen names it, in the reader's language.

    A refusal in a Polish sentence said "Okres 2026-09" about the month the
    screen calls "wrzesień 2026": the same period under a name the reader has
    to translate before finding it on the list.
    """
    # Babel spells a locale with an underscore; ``pt-BR`` is how a language is
    # stored here.
    locale = get_current_lang().replace('-', '_')
    return format_date(date(year, month, 1), 'LLLL y', locale=locale)


async def is_period_closed(db: AsyncSession, org_id: UUID, doc_date: date) -> bool:
    result = await db.scalars(
        select(InventoryPeriod).where(
            InventoryPeriod.organization_id == org_id,
            InventoryPeriod.year == doc_date.year,
            InventoryPeriod.month == doc_date.month,
            InventoryPeriod.closed_at.isnot(None),
        )
    )
    period = result.first()
    return period is not None and period_is_closed(period)


async def get_period(
    db: AsyncSession, org_id: UUID, year: int, month: int
) -> InventoryPeriod:
    await acquire_advisory_lock(db, f'inventory_period:{org_id}:{year}:{month}')
    result = await db.scalars(
        select(InventoryPeriod).where(
            InventoryPeriod.organization_id == org_id,
            InventoryPeriod.year == year,
            InventoryPeriod.month == month,
        )
    )
    period = result.first()
    if period is None:
        period = InventoryPeriod(
            organization_id=org_id,
            year=year,
            month=month,
        )
        db.add(period)
        await db.flush()
    return period


async def _period_to_dict(db: AsyncSession, period: InventoryPeriod) -> dict[str, Any]:
    return {
        'id': period.id,
        'year': period.year,
        'month': period.month,
        # Stated rather than inferred. Readers used to take a non-NULL
        # ``closed_at`` for "closed", which is why reopening had to erase it.
        'is_closed': period_is_closed(period),
        'closed_at': period.closed_at,
        'closed_by': await _get_user_name(db, period.organization_id, period.closed_by),
        'reopened_at': period.reopened_at,
        'reopened_by': await _get_user_name(
            db, period.organization_id, period.reopened_by
        ),
        'notes': period.notes,
    }


async def _log_period_event(
    db: AsyncSession,
    org_id: UUID,
    period: InventoryPeriod,
    user_id: UUID,
    *,
    closed: bool,
    notes: str | None,
) -> None:
    """Put the closing — or the undoing of it — in the organization log.

    The row holds the current state and the last stamp of each kind; the log
    holds the sequence. A month closed in March, reopened in June and closed
    again in July leaves three entries here and one row there, and only the
    three entries can answer "who reopened my closed books, and when".
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.INVENTORY_PERIOD,
        target_id=period.id,
        snapshot={
            'name': f'{period.year}-{period.month:02d}',
            'before': {'closed': not closed},
            'after': {'closed': closed},
        },
        reason=notes,
    )


async def close_period(
    db: AsyncSession,
    org_id: UUID,
    year: int,
    month: int,
    user_id: UUID,
    notes: str | None = None,
) -> dict[str, Any]:
    period = await get_period(db, org_id, year, month)
    if period_is_closed(period):
        raise ServiceRejectionError(
            'period_already_closed', period=period_label(year, month)
        )
    period.closed_at = datetime.now(UTC)
    period.closed_by = user_id
    period.notes = notes
    await _log_period_event(db, org_id, period, user_id, closed=True, notes=notes)
    await db.flush()
    return await _period_to_dict(db, period)


async def reopen_period(
    db: AsyncSession,
    org_id: UUID,
    year: int,
    month: int,
    user_id: UUID,
    notes: str | None = None,
) -> dict[str, Any]:
    period = await get_period(db, org_id, year, month)
    if not period_is_closed(period):
        raise ServiceRejectionError(
            'period_not_closed', period=period_label(year, month)
        )
    period.reopened_at = datetime.now(UTC)
    period.reopened_by = user_id
    period.notes = notes
    await _log_period_event(db, org_id, period, user_id, closed=False, notes=notes)
    await db.flush()
    return await _period_to_dict(db, period)


async def list_periods(
    db: AsyncSession,
    org_id: UUID,
    *,
    year: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """One page of the organization's periods, newest first, and the full count."""
    query = select(InventoryPeriod).where(InventoryPeriod.organization_id == org_id)
    if year is not None:
        query = query.where(InventoryPeriod.year == year)
    periods, total = await paginate_async(
        db,
        query.order_by(desc(InventoryPeriod.year), desc(InventoryPeriod.month)),
        limit=limit,
        offset=offset,
    )
    return [await _period_to_dict(db, p) for p in periods], total


async def _refuse_a_closed_period_async(
    db: AsyncSession, org_id: UUID, on: date, sentence: str
) -> None:
    if await is_period_closed(db, org_id, on):
        raise PeriodClosedError(
            get_error_message(
                sentence, get_current_lang(), period=period_label(on.year, on.month)
            )
        )


async def check_period_not_closed_async(
    db: AsyncSession,
    org_id: UUID,
    doc_date: date,
) -> None:
    """Async guard for async lifecycle functions."""
    await _refuse_a_closed_period_async(db, org_id, doc_date, 'period_closed_for_date')


async def check_stock_change_period_open_async(
    db: AsyncSession, org_id: UUID, on: date
) -> None:
    """The guard Core's stock doors ask, through the period-guard registry.

    A scan, a move, a quantity change or an import lands on the day it is
    made: the person has no date to change, so the refusal sends them to
    whoever may reopen the period rather than to a document date that the
    screen they are on does not have.
    """
    await _refuse_a_closed_period_async(
        db, org_id, on, 'period_closed_for_stock_change'
    )
