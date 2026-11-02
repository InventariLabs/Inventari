"""The door to an existing WMS session: under this document, owned by this user.

A session row names exactly one document and one user. The URL names the
document again, and the caller is whoever holds the token; both facts are
checked here, once, so every operation past ``start`` answers the same way
instead of each router remembering its own half. A session that is not under
the URL's document is 404 — the resource is not there to operate on — and a
session somebody else opened is 409 ``SESSION_HELD_BY_OTHER_USER`` carrying
the holder's name and the session id: the same refusal ``start`` already
gives and the release dialog already reads, so a session refused here can be
released through the release door exactly like a held document.

The owner-only rule is deliberate (session operations belong to the person
holding the session; another person's work enters through a named act, never
through a silent scan). Two acts cross the ownership line, both open to
anyone who may write documents: ``take_over_session_async`` moves the
session with its scans to the caller, and ``release`` puts it back and
discards them. ``cancel`` is the holder's own way out of their session.
Every door asks for the document, never for the owner.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
)
from app.core.public_api import core_api

from ._wms_line_utils import session_document_ids_async
from ._wms_session_close import journal_session_async
from ._wms_session_ops import SessionHeldByOtherUserError
from .models import WmsPickSession


async def _holder_name_async(
    db: AsyncSession, org_id: UUID, assigned_to: UUID | None
) -> str:
    """The holder's display name, worded as ``start``'s refusal words it."""
    holder = (
        await core_api.users.get_async(db, org_id, assigned_to)
        if assigned_to is not None
        else None
    )
    return (
        (holder.full_name if holder else None)
        or (holder.email if holder else None)
        or 'unknown'
    )


def _session_held_conflict(exc: SessionHeldByOtherUserError) -> ConflictException:
    """The 409 envelope ``start`` and the operation door both answer with."""
    return ConflictException(
        'SESSION_HELD_BY_OTHER_USER',
        str(exc),
        details={
            'held_session_id': str(exc.session_id),
            'held_by': exc.owner,
        },
    )


async def _get_session_for_document_async(
    db: AsyncSession,
    *,
    session_id: UUID,
    document_id: UUID,
    org_id: UUID,
    resource: str,
) -> WmsPickSession:
    """The document's session, or 404 — the URL names both, they must agree.

    Loads regardless of session status: ``complete`` answers an already
    finished session idempotently, so its door must reach the row the
    operation will read, not only an active one. The lines ride along so the
    read endpoints can answer from the row this returns. A session over
    several dispatches is reached through any of them.
    """
    session = await db.scalar(
        select(WmsPickSession)
        .where(
            WmsPickSession.id == session_id,
            WmsPickSession.organization_id == org_id,
        )
        .options(selectinload(WmsPickSession.lines))
    )
    if session is None:
        raise NotFoundException(resource)
    if session.document_id != document_id and document_id not in (
        await session_document_ids_async(db, session)
    ):
        raise NotFoundException(resource)
    return session


async def _get_owned_session_for_document_async(
    db: AsyncSession,
    *,
    session_id: UUID,
    document_id: UUID,
    org_id: UUID,
    user_id: UUID,
    resource: str,
) -> WmsPickSession:
    """As above, and 409 when somebody else holds the session now.

    The sentence says the session is held by the other person, not that they
    opened it: a screen that kept scanning after a handover meets this refusal,
    and it has to tell its reader who has the session and that its scans stop.
    """
    session = await _get_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        resource=resource,
    )
    if session.assigned_to != user_id:
        exc = SessionHeldByOtherUserError(
            session.id,
            await _holder_name_async(db, org_id, session.assigned_to),
            key='wms_session_now_held_by',
        )
        raise _session_held_conflict(exc) from exc
    return session


async def take_over_session_async(
    db: AsyncSession,
    session: WmsPickSession,
    user_id: UUID,
    *,
    finished: bool = False,
) -> None:
    """Move an open session, with every scan on it, to *user_id*.

    The act for the colleague who finishes what somebody else began: the
    lines keep their tallies, only the holder changes. Both names go into the
    audit log beside the session's documents, so the record says who handed
    what to whom. Taking over one's own session is a no-op and writes nothing.
    A session that is already closed has nothing left to hand over, unless
    *finished* says it is the summary being handed on: the one the document's
    start returns to whoever opens it, whose Undo skip and answers go through
    the holder's door and would otherwise refuse everybody but the person who
    skipped.
    """
    if not finished and session.status not in ('active', 'paused'):
        raise ServiceRejectionError('wms_session_not_found')
    if session.assigned_to == user_id:
        return
    org_id = session.organization_id
    previous = await _holder_name_async(db, org_id, session.assigned_to)
    current = await _holder_name_async(db, org_id, user_id)
    session.assigned_to = user_id
    await db.flush()
    await journal_session_async(
        db,
        session,
        user_id,
        extra={
            'wms_session_handed_over_from': previous,
            'wms_session_handed_over_to': current,
        },
    )
