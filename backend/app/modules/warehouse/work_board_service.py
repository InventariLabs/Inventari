"""The strip above the work board: this week's work, counted from the records.

Nothing is typed in for these numbers. A delivery's first scan opens a
receiving session and its posting stamps the document, so the time between
them is how long goods stood on the dock; a dispatch carries the day it was
raised and the moment it was posted, so whether it left the same day is read
off the document. The week is the organization's own, Monday to now, on its
own clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from . import document_types as dt
from ._schemas_work_items import WorkItemMeasures
from .models import Document, DocumentStatus, WmsPickSession


async def work_measures_async(
    db: AsyncSession, org_id: UUID, *, now: datetime | None = None
) -> WorkItemMeasures:
    """Dock-to-stock time and same-day shipping for the week so far."""
    tz = await core_api.organizations.timezone_async(db, org_id)
    local_now = (now or datetime.now(UTC)).astimezone(tz)
    monday = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_start = monday.astimezone(UTC)

    first_scan = (
        select(
            WmsPickSession.document_id.label('document_id'),
            func.min(WmsPickSession.started_at).label('started_at'),
        )
        .where(
            WmsPickSession.organization_id == org_id,
            WmsPickSession.status != 'cancelled',
        )
        .group_by(WmsPickSession.document_id)
        .subquery()
    )
    receipts = (
        await db.execute(
            select(Document.completed_at, first_scan.c.started_at)
            .join(first_scan, first_scan.c.document_id == Document.id)
            .where(
                Document.organization_id == org_id,
                Document.status == DocumentStatus.COMPLETED.value,
                Document.type == dt.IN,
                Document.completed_at >= week_start,
            )
        )
    ).all()
    spans = [
        (completed - started).total_seconds()
        for completed, started in receipts
        if completed >= started
    ]

    shipped = (
        await db.execute(
            select(Document.created_at, Document.completed_at).where(
                Document.organization_id == org_id,
                Document.status == DocumentStatus.COMPLETED.value,
                Document.type == dt.OUT,
                Document.completed_at >= week_start,
            )
        )
    ).all()
    same_day = sum(
        1
        for created, completed in shipped
        if created.astimezone(tz).date() == completed.astimezone(tz).date()
    )

    return WorkItemMeasures(
        dock_to_stock_seconds=round(sum(spans) / len(spans)) if spans else None,
        dock_to_stock_count=len(spans),
        shipped_same_day=same_day,
        shipped_total=len(shipped),
    )
