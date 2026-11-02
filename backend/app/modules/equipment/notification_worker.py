"""
Scheduled worker for equipment in-app notifications.

Checks for:
- Warranty expiring within N days
- Overdue checkouts (past expected_return_at)
- Upcoming maintenance (next_maintenance_at within N days)

Uses core_api.notifications.notify_org_admins() for in-app alerts.
"""

from datetime import UTC, date, datetime, timedelta, tzinfo
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import NotificationDedupKey
from app.core.logging import get_logger
from app.core.public_api import core_api

from . import _notification_labels as _labels
from ._holder import PLACE, holder_of_assignment
from .models import EquipmentAssignment, EquipmentMaintenanceLog

logger = get_logger(__name__)


def _as_date(value: date | datetime, tz: tzinfo | None = None) -> date:
    """Coerce ``datetime`` → ``date`` so day-level comparisons are safe.

    Python's ``datetime`` is a subclass of ``date``, so ``isinstance(x, date)``
    is true for both — but ``datetime < date`` raises ``TypeError`` because the
    comparison requires matching types. Several SQLAlchemy columns here are
    typed ``DateTime(timezone=True)`` and round-trip as ``datetime``;
    we strip the time component before any day-level arithmetic.

    With *tz*, the day is read on that clock: the expected return is pinned
    to the end of its day on the organization's calendar (review
    2026-09-23), so its UTC date is the next day for every organization
    west of UTC, while the worker compares against the organization's
    today.
    """
    if isinstance(value, datetime):
        if tz is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(tz).date()
        return value.date()
    return value


async def run_notification_check_self_contained() -> None:
    """Self-contained async worker — creates its own AsyncSession."""
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        logger.warning(
            '[equipment] AsyncSessionLocal not initialized; skipping notification check'
        )
        return
    async with db_facade.AsyncSessionLocal() as db:
        await run_equipment_notification_check_async(db)


WARRANTY_WARNING_DAYS = 30
MAINTENANCE_WARNING_DAYS = 7


async def _already_notified_today(
    db: AsyncSession, org_id: UUID, key: NotificationDedupKey
) -> bool:
    """Dedup guard: True when an unread alert with the same natural key
    (org + reference + notification type) was already created today.

    Without this, every worker tick (and every app worker in a cluster)
    re-inserts identical notifications for the same condition.
    """
    # "Today" is the organization's day, not the server's — otherwise the
    # dedup window opens and closes hours away from the day the reader sees,
    # and a warning is either repeated or swallowed around the boundary.
    today_start = await core_api.organizations.window_start_async(db, org_id, 0)
    return await core_api.notifications.exists_unread_by_meta_async(
        db, org_id, key, since=today_start
    )


async def _get_warning_windows(db: AsyncSession, org_id: UUID) -> tuple[int, int]:
    """Read per-org warning windows from module settings, falling back to defaults."""
    settings = await core_api.settings.get_async(db, org_id, 'equipment') or {}
    warranty_days = settings.get('warranty_warning_days', WARRANTY_WARNING_DAYS)
    maintenance_days = settings.get(
        'maintenance_warning_days', MAINTENANCE_WARNING_DAYS
    )
    return warranty_days, maintenance_days


async def run_equipment_notification_check_async(db: AsyncSession) -> None:
    """Scan all equipment-enabled orgs and fire in-app notifications.

    Commits per org: ``create_async`` only flushes, and the caller's session
    is never committed by the scheduler path — without these commits the
    worker's notifications were silently rolled back on session close.
    The except path rolls back so a mid-org failure cannot leak partial
    rows into the next org's commit.
    """
    all_orgs = await core_api.organizations.list_all_async(db)
    for org in all_orgs:
        if not await core_api.organizations.is_module_enabled_async(
            db, org.id, 'equipment'
        ):
            continue
        try:
            warranty_days, maintenance_days = await _get_warning_windows(db, org.id)
            await _check_warranty_async(db, org.id, days=warranty_days)
            await _check_overdue(db, org.id)
            await _check_maintenance(db, org.id, days=maintenance_days)
            await db.commit()
        except Exception:  # worker loop must never crash
            await db.rollback()
            logger.exception('[equipment] notification check failed for org %s', org.id)


async def _check_warranty_async(db: AsyncSession, org_id: UUID, days: int) -> None:
    from .dashboard_service import get_warranty_alerts

    alerts = await get_warranty_alerts(db, org_id, days=days)
    for alert in alerts:
        if await _already_notified_today(
            db,
            org_id,
            NotificationDedupKey(
                meta_type='equipment_warranty',
                ref_key='item_id',
                ref_id=str(alert.item_id),
            ),
        ):
            continue
        notifications = await core_api.notifications.notify_org_admins_async(
            db,
            org_id,
            title=core_api.notifications.localize(
                _labels.WARRANTY_TITLE, item=alert.item_name
            ),
            # The serial-number fallback is part of the sentence, so it is
            # chosen in the same language the sentence is written in.
            content={
                lang: text.format(
                    item=alert.item_name,
                    serial=alert.serial_number or _labels.NO_SERIAL[lang],
                    days=alert.days_remaining,
                    date=alert.warranty_until.isoformat(),
                )
                for lang, text in _labels.WARRANTY_CONTENT.items()
            },
            notification_type='warning',
            link=f'/equipment?highlight={alert.item_id}',
            meta_data={
                'type': 'equipment_warranty',
                'item_id': str(alert.item_id),
                'days_remaining': alert.days_remaining,
            },
        )
        await core_api.notifications.publish_async(db, notifications)


async def _check_overdue(db: AsyncSession, org_id: UUID) -> None:
    now = await core_api.organizations.today_async(db, org_id)
    org_tz = await core_api.organizations.timezone_async(db, org_id)
    result = await db.stream(
        select(EquipmentAssignment).where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
            EquipmentAssignment.expected_return_at.isnot(None),
        )
    )
    async for assignment in result.scalars():
        expected = assignment.expected_return_at
        if expected is None:
            continue
        expected_day = _as_date(expected, org_tz)
        if expected_day < now:
            if await _already_notified_today(
                db,
                org_id,
                NotificationDedupKey(
                    meta_type='equipment_overdue',
                    ref_key='assignment_id',
                    ref_id=str(assignment.id),
                ),
            ):
                continue
            days_overdue: int = (now - expected_day).days
            item_name = assignment.item.name if assignment.item else None
            names = {
                lang: item_name or _labels.UNKNOWN_ITEM[lang]
                for lang in _labels.OVERDUE_TITLE
            }
            # Who or what holds it, by the one definition every surface
            # reads. A deployment's holder is a place and the sentence says
            # so; a legacy row naming neither still reads without a hole.
            holder = holder_of_assignment(assignment)
            templates = (
                _labels.OVERDUE_CONTENT_LOCATION
                if holder is not None and holder.kind == PLACE
                else _labels.OVERDUE_CONTENT
            )
            notifications = await core_api.notifications.notify_org_admins_async(
                db,
                org_id,
                title={
                    lang: text.format(item=names[lang])
                    for lang, text in _labels.OVERDUE_TITLE.items()
                },
                content={
                    lang: templates[lang].format(
                        item=names[lang],
                        holder=(
                            holder.name
                            if holder is not None
                            else _labels.UNKNOWN_HOLDER[lang]
                        ),
                        days=days_overdue,
                    )
                    for lang in templates
                },
                notification_type='warning',
                link=f'/equipment/{assignment.item_id}',
                meta_data={
                    'type': 'equipment_overdue',
                    'assignment_id': str(assignment.id),
                    'item_id': str(assignment.item_id),
                    'days_overdue': days_overdue,
                },
            )
            await core_api.notifications.publish_async(db, notifications)


async def _get_equipment_item_ids(db: AsyncSession, org_id: UUID) -> set[UUID]:
    """Ids of the records the equipment module counts as its own.

    Read through the same items listing the dashboard and the fleet
    valuation read, because the seeded category codes answered a narrower
    question: an asset filed under no category, which the equipment form
    never required, carried a maintenance entry whose reminder never fired.
    The cap mirrors the dashboard's aggregation cap.
    """
    items = await core_api.items.list_async(
        db, org_id, context_tag='equipment', limit=10000
    )
    return {item.id for item in items}


async def _check_maintenance(db: AsyncSession, org_id: UUID, days: int) -> None:
    today = await core_api.organizations.today_async(db, org_id)
    window = today + timedelta(days=days)

    eq_item_ids = await _get_equipment_item_ids(db, org_id)
    if not eq_item_ids:
        return

    result = await db.stream(
        select(EquipmentMaintenanceLog).where(
            EquipmentMaintenanceLog.organization_id == org_id,
            EquipmentMaintenanceLog.item_id.in_(eq_item_ids),
            EquipmentMaintenanceLog.next_maintenance_at.isnot(None),
        )
    )
    async for log in result.scalars():
        next_date_raw = log.next_maintenance_at
        if next_date_raw is None:
            continue
        next_date = _as_date(next_date_raw)
        if today <= next_date <= window:
            if await _already_notified_today(
                db,
                org_id,
                NotificationDedupKey(
                    meta_type='equipment_maintenance',
                    ref_key='log_id',
                    ref_id=str(log.id),
                ),
            ):
                continue
            days_until = (next_date - today).days
            item_name = log.item.name if log.item else None
            names = {
                lang: item_name or _labels.UNKNOWN_ITEM[lang]
                for lang in _labels.MAINTENANCE_TITLE
            }
            notifications = await core_api.notifications.notify_org_admins_async(
                db,
                org_id,
                title={
                    lang: text.format(item=names[lang])
                    for lang, text in _labels.MAINTENANCE_TITLE.items()
                },
                content={
                    lang: text.format(
                        item=names[lang],
                        kind=log.maintenance_type.lower(),
                        days=days_until,
                        date=next_date.isoformat(),
                    )
                    for lang, text in _labels.MAINTENANCE_CONTENT.items()
                },
                notification_type='warning',
                link=f'/equipment/{log.item_id}',
                meta_data={
                    'type': 'equipment_maintenance',
                    'log_id': str(log.id),
                    'item_id': str(log.item_id),
                    'days_until': days_until,
                },
            )
            await core_api.notifications.publish_async(db, notifications)
