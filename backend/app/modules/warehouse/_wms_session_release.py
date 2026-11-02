"""A scanning session nobody is working in stops holding its document.

Closing the picking or receiving sheet used to leave the session open and
held by whoever closed it: the document then refused completion and
cancellation, and the page offered a resume or a discard of every scan. A
worker who walked away from the sheet had blocked the document for
everyone.

A session is released when its holder closes the sheet (``paused``), or when
nobody has scanned in it for the organization's idle time. A released
session keeps every scan — they are already the document lines' done
quantities — and asks nothing of anyone: whoever starts the document next
continues it, taking it over when somebody else began it, and completing the
document books what was scanned and closes the session with it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._wms_direction import PICKING, RECEIVING
from ._wms_session_close import (
    RESOLVED_STATUSES,
    journal_session_async,
    pin_picked_lots_async,
)
from .models import DocumentLine, WmsPickLine, WmsPickSession

#: The organization setting this module reads, stored under
#: ``module:warehouse`` through the module settings schema.
IDLE_SETTING_KEY = 'scan_session_idle_minutes'
DEFAULT_IDLE_MINUTES = 30


async def idle_minutes_async(db: AsyncSession, org_id: UUID) -> int:
    """How long a session may stand untouched, 30 minutes by default.

    A stored value that is not a positive whole number reads as the default.
    """
    raw = await core_api.settings.get_async(
        db, org_id, 'warehouse', IDLE_SETTING_KEY, default=DEFAULT_IDLE_MINUTES
    )
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MINUTES
    return minutes if minutes > 0 else DEFAULT_IDLE_MINUTES


async def session_released_async(db: AsyncSession, session: WmsPickSession) -> bool:
    """Whether an open session holds its document no longer."""
    if session.status == 'paused':
        return True
    if session.status != 'active':
        return False
    last = session.last_activity_at or session.started_at
    idle = timedelta(minutes=await idle_minutes_async(db, session.organization_id))
    return last < datetime.now(UTC) - idle


async def settle_released_session_async(
    db: AsyncSession, session: WmsPickSession, document_id: UUID, user_id: UUID
) -> None:
    """Let the document go from a released session with what was scanned.

    The document's lines the session never finished are answered by their
    scans: a line with something scanned is short by the rest, a line with
    nothing is skipped. The quantities themselves are the document's
    already, and the completion that follows decides what is booked. A
    receipt line short of its goods says so, they never came; a picking line
    says nothing, nobody chose what its shortfall becomes, and the completion
    that follows asks. A picking line hands its batches to the document line,
    as a closing does. The session ends when it has nothing left for any
    other document.
    """
    pairs = (
        await db.execute(
            select(WmsPickLine, DocumentLine)
            .join(DocumentLine, DocumentLine.id == WmsPickLine.document_line_id)
            .where(
                WmsPickLine.session_id == session.id,
                DocumentLine.document_id == document_id,
            )
            .with_for_update(of=WmsPickLine)
        )
    ).all()
    lines = [line for line, _ in pairs]
    inbound = (session.meta_data or {}).get('direction') == 'inbound'
    for line, doc_line in pairs:
        if line.status != 'pending':
            continue
        line.status = 'short' if line.picked_quantity > 0 else 'skipped'
        # A receipt line says so on the document too, as a short count or a
        # skip writes it: a line still at nothing with no reason would read
        # as one nobody answered for, and completion would refuse it.
        if inbound and doc_line.done_quantity < doc_line.expected_quantity:
            doc_line.discrepancy_code = doc_line.discrepancy_code or 'SHORTAGE'
    if not inbound:
        await pin_picked_lots_async(db, lines)

    statuses = (
        await db.scalars(
            select(WmsPickLine.status).where(WmsPickLine.session_id == session.id)
        )
    ).all()
    if all(status in RESOLVED_STATUSES for status in statuses):
        direction = RECEIVING if inbound else PICKING
        short = any(status == 'short' for status in statuses)
        session.status = direction.short_status if short else 'completed'
        session.completed_at = datetime.now(UTC)
    await db.flush()
    await journal_session_async(db, session, user_id)


async def pause_session_async(
    db: AsyncSession, session: WmsPickSession, user_id: UUID
) -> None:
    """The holder closed the sheet: the session stops holding its document.

    Nothing is put back — the scans stay on the lines and on the document —
    and the next start continues it, whoever asks. The journal says the
    session was left paused, which is what the next person to open the
    document finds. A session that already ended has nothing to pause.
    """
    if session.status == 'active':
        session.status = 'paused'
        await db.flush()
        await journal_session_async(db, session, user_id)
