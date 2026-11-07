"""One session machine for both WMS directions.

Picking and receiving were written as sibling modules — five operations
each, near-verbatim — and the copies drifted: the empty-session guard on
complete and the quantity-based undo filter each existed on one side only.
This module holds the machine; ``_picking_session_ops`` and
``_receiving_session_ops`` bind it to their direction's vocabulary
(``_wms_direction``) and keep their public names.

The stored line status is the same for both directions ('picked'), because
both write the same table; only the wire word differs (``done_word``).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from ._over_receipt import SURPLUS_CODE, is_surplus
from ._po_receipt_guard import assert_line_over_receipt_allowed_async
from ._wms_direction import PICKING, RECEIVING, WmsDirection
from ._wms_line_utils import (
    _get_active_session_async,
    _resolve_lot_name,
    _resolve_product_name,
    _resolve_uom_symbol,
    mark_worked_on,
    session_holds_document,
)
from ._wms_session_close import (
    DESTINATION_KEY,
    RESOLVED_STATUSES,
    close_session_if_complete_async,
    destination_awaited,
    forget_lot_tallies_async,
    journal_session_async,
    pin_picked_lots_async,
    rollback_session_lines_async,
)
from ._wms_session_release import session_released_async
from ._wms_shelf import CONFIRM_KEY
from .document_profile_service import get_profile
from .models import (
    QUARANTINE_CODES,
    Document,
    DocumentLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
    WmsPickSessionDocument,
)
from .packing_service import (
    assert_packed_within_quantity_async,
    assert_pick_not_packed_async,
)

#: A direction's gate for the document types a session may start on.
SupportsDocType = Callable[[str], bool]
#: The extra fields a direction fills on each session line as it is built.
#: The document carries the organization, so the callback is not handed it
#: beside: a direction with nothing to plan takes nothing it does not read.
LineFields = Callable[[AsyncSession, DocumentLine, Document], Awaitable[dict[str, Any]]]
#: A direction's re-ordering of the lines it just built, when it has one.
SortLines = Callable[[AsyncSession, UUID], Awaitable[None]]


class SessionHeldByOtherUserError(ServiceRejectionError):
    """A document's active session belongs to someone else.

    Carries what the interface needs to offer a way out: the id of the
    session holding the document — the take-over and release doors take it —
    and the holder's name, so the reader knows whose recorded scans a release
    discards. Routers map it to 409 ``SESSION_HELD_BY_OTHER_USER`` with
    both in the detail envelope; the flat ``ValueError`` it replaces
    reached the page as an unstructured sentence and left the document
    unreachable for everyone but its owner.
    """

    def __init__(
        self,
        session_id: UUID,
        owner: str,
        key: str = 'wms_session_held_by_other_user',
    ) -> None:
        self.session_id = session_id
        self.owner = owner
        super().__init__(key, owner=owner)


async def _line_document_async(db: AsyncSession, line: WmsPickLine) -> Document | None:
    """The document a session line answers for — its own, not the session's."""
    return cast(
        Document | None,
        await db.scalar(
            select(Document)
            .join(DocumentLine, DocumentLine.document_id == Document.id)
            .where(DocumentLine.id == line.document_line_id)
        ),
    )


async def _refuse_unless_line_document_open_async(
    db: AsyncSession, line: WmsPickLine
) -> None:
    """Refuse to rewrite a line whose document has been closed.

    A session over several dispatches lets each go as its lines resolve, and
    the released one may be completed or cancelled while the session goes on
    for the others. Its lines are then that document's record: changing a
    tally on them would change a completed document behind its back.
    """
    doc = await _line_document_async(db, line)
    if doc is not None and doc.status != DocumentStatus.CONFIRMED.value:
        raise ServiceRejectionError(
            'wms_line_document_closed', number=doc.number, status=doc.status
        )


async def _reopen_for_skipped_line_async(
    db: AsyncSession,
    direction: WmsDirection,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
) -> WmsPickSession | None:
    """Open a finished session again for a skipped line its summary answers.

    Skipping the last open line ends the session, and the summary that
    follows offers the skip back, or a short pick of nothing under the code
    the person chooses. A skip recorded nothing, so the session loses
    nothing by taking either answer. Only the session the document's
    summary comes back to reopens -- its latest, from the current
    confirmation, the document still confirmed -- and only for a skipped
    line of it; anything else is left to the active-session guard.
    Answers the session it reopened, or ``None`` when it reopened nothing.
    """
    session = await db.scalar(
        select(WmsPickSession)
        .where(
            WmsPickSession.id == session_id,
            WmsPickSession.organization_id == org_id,
            WmsPickSession.status.in_(('completed', direction.short_status)),
        )
        .with_for_update()
    )
    if session is None:
        return None
    line = await db.scalar(
        select(WmsPickLine).where(
            WmsPickLine.id == line_id,
            WmsPickLine.session_id == session_id,
            WmsPickLine.status == 'skipped',
        )
    )
    doc = await _line_document_async(db, line) if line is not None else None
    if doc is None or doc.status != DocumentStatus.CONFIRMED.value:
        return None
    latest = await _finished_session_of_async(db, direction, org_id, doc)
    if latest is None or latest.id != session.id:
        return None
    session.status = 'active'
    session.completed_at = None
    return session


def _refuse_a_shortfall_nobody_chose(
    direction: WmsDirection,
    line: WmsPickLine,
    quantity: Decimal,
    discrepancy_code: str | None,
) -> None:
    """A pick that comes up short is a decision, and says which.

    The shortage owes the rest on a backorder, any other reason closes the
    gap. Receiving names the shortage itself when nothing else is said, the
    goods never came; a picker's shortfall is never a default.
    """
    if (
        direction.kind == PICKING.kind
        and quantity < line.expected_quantity
        and not discrepancy_code
    ):
        raise ServiceRejectionError('wms_short_pick_needs_outcome')


async def confirm_short_async(
    db: AsyncSession,
    direction: WmsDirection,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    quantity: Decimal,
    discrepancy_code: str | None = None,
    discrepancy_reason: str | None = None,
    may_exceed_over_receipt: bool | None = None,
    *,
    replace_scans: bool = False,
    held_quantity: Decimal = Decimal('0'),
) -> WmsPickLine:
    """Confirm a line with the final quantity that was actually handled.

    The quantity is the line's total after the count, not what the last
    scan added: the dialog prefills it with the quantity already scanned,
    and the worker corrects it to the number they counted.

    *may_exceed_over_receipt* is receiving's policy switch, as in
    ``_wms_scan_ops.execute_scan_async``: ``None`` refuses a quantity over
    the line's expected figure outright, while a boolean allows the
    over-receipt tolerance and says whether the caller holds the permission
    to go past it.

    *replace_scans* says the caller counted less than the scans already
    recorded and means that count to supersede them. Without it a total
    below the scanned quantity is refused, rather than silently discarding
    what a worker scanned.

    *held_quantity* is receiving's answer to how much of that total is
    received but not usable — damaged or on a quality hold. It travels on
    the document line, which the stock executor reads to keep those goods
    off the shelf and out of the order's received figure.
    """
    await _reopen_for_skipped_line_async(db, direction, session_id, org_id, line_id)
    session = await _get_active_session_async(db, session_id, org_id)

    line = await db.scalar(
        select(WmsPickLine)
        .where(
            WmsPickLine.id == line_id,
            WmsPickLine.session_id == session_id,
        )
        .with_for_update()
        # The session may already be in this request's identity map, and a
        # scan committed while this call waited for the lock would leave
        # that copy stale. The guard below compares against the scanned
        # total, so it must read what the last writer left.
        .execution_options(populate_existing=True)
    )
    if not line:
        raise ServiceRejectionError('wms_line_not_found')
    await _refuse_unless_line_document_open_async(db, line)

    # Zero is an answer — nothing arrived — and it is negative quantities
    # that cannot be true of a line's tally. The dialog at the other end of
    # this call used to refuse zero as well, which sent "nothing came of
    # this line" down the one road that had no way to record it.
    if quantity < 0:
        raise ServiceRejectionError('wms_quantity_cannot_be_negative')

    # The count is the line's final total, so it may sit on or above what
    # the scans recorded, never silently below it: a count under the scans
    # has to say that it supersedes them, or the record would lose goods a
    # worker had already handled without anyone agreeing to it.
    if quantity < line.picked_quantity and not replace_scans:
        raise ServiceRejectionError(
            'wms_short_below_scanned', scanned=line.picked_quantity
        )

    if held_quantity < 0:
        raise ServiceRejectionError(
            'document_held_quantity_negative', quantity=held_quantity
        )
    if held_quantity > quantity:
        raise ServiceRejectionError(
            'document_held_quantity_above_received',
            quantity=held_quantity,
            received=quantity,
        )
    if held_quantity:
        if direction.kind != RECEIVING.kind:
            raise ServiceRejectionError('document_held_quantity_needs_receipt')
        if discrepancy_code not in QUARANTINE_CODES:
            raise ServiceRejectionError('document_held_quantity_needs_code')

    doc_line = await db.scalar(
        select(DocumentLine).where(
            DocumentLine.id == line.document_line_id,
        )
    )

    _refuse_a_shortfall_nobody_chose(direction, line, quantity, discrepancy_code)

    over_expected = is_surplus(doc_line, quantity, line.expected_quantity)
    if over_expected:
        if may_exceed_over_receipt is None:
            raise ServiceRejectionError('wms_quantity_above_expected')
        await assert_line_over_receipt_allowed_async(
            db,
            org_id,
            doc_line,
            exclude_doc_id=doc_line.document_id if doc_line else None,
            quantity=quantity,
            expected=line.expected_quantity,
            may_exceed=may_exceed_over_receipt,
        )

    # The count may not settle the line below what a package already holds:
    # the box would say more left than the dispatch ships. Asked here, at
    # the dialog, rather than left for completion to discover — a receipt
    # has no packages, so the guard passes it by.
    await assert_packed_within_quantity_async(db, doc_line, quantity)

    line.picked_quantity = quantity
    line.status = 'short' if quantity < line.expected_quantity else 'picked'

    if doc_line:
        doc_line.done_quantity = quantity
        if line.status == 'short':
            # A partial says why, wherever it was entered. The panel
            # has always demanded a code and a skip writes one; here
            # it was optional, so a short line could reach completion
            # unexplained — and then be read as a line nobody had
            # answered for. Naming the shortage is the honest default;
            # whoever knows more overwrites it. The name is the code,
            # which every screen reads in the reader's language — the
            # sentence it used to store was English in all of them.
            doc_line.discrepancy_code = discrepancy_code or 'SHORTAGE'
            doc_line.discrepancy_reason = discrepancy_reason
        elif over_expected:
            # A surplus says why too — the code travels with the line, and
            # completion keeps it (see ``_default_execution_quantities``).
            doc_line.discrepancy_code = discrepancy_code or SURPLUS_CODE
            doc_line.discrepancy_reason = discrepancy_reason
        elif held_quantity:
            # A full delivery can still hold goods back; the code says why
            # even though the line itself is not short.
            doc_line.discrepancy_code = discrepancy_code
            doc_line.discrepancy_reason = discrepancy_reason
        doc_line.held_quantity = (
            held_quantity if direction.kind == RECEIVING.kind else Decimal('0')
        )

    # a short line resolving the last pending line ends the session.
    await close_session_if_complete_async(
        db, session, short_status=direction.short_status
    )

    await db.flush()
    await db.refresh(line)
    return line


async def complete_session_async(
    db: AsyncSession,
    direction: WmsDirection,
    session_id: UUID,
    org_id: UUID,
) -> WmsPickSession:
    # scans, shorts and skips close the session themselves once the last
    # line resolves, so the explicit complete endpoint has to answer the
    # same thing twice instead of failing with "no active session".
    session = await db.scalar(
        select(WmsPickSession).where(
            WmsPickSession.id == session_id,
            WmsPickSession.organization_id == org_id,
        )
    )
    if not session:
        raise ServiceRejectionError('wms_session_not_found')
    if session.status in ('completed', direction.short_status):
        await db.refresh(session, ['lines'])
        return session
    if session.status not in ('active', 'paused'):
        raise ServiceRejectionError('wms_session_not_found')

    lines = (
        await db.scalars(
            select(WmsPickLine)
            .where(WmsPickLine.session_id == session_id)
            .with_for_update()
        )
    ).all()

    # A session with no lines resolves vacuously — `all([])` is True — so
    # without this guard an empty session reports completion over a document
    # whose lines are all still pending. It used to sit on the picking side
    # only, and the receiving copy answered success for the empty session.
    if not lines:
        raise ServiceRejectionError('wms_cannot_complete_no_lines')

    all_resolved = all(ln.status in RESOLVED_STATUSES for ln in lines)
    if not all_resolved:
        pending = sum(1 for ln in lines if ln.status == 'pending')
        raise ServiceRejectionError('wms_cannot_complete_lines_pending', count=pending)
    if destination_awaited(session, lines) is not None:
        raise ServiceRejectionError('wms_cannot_complete_destination_not_scanned')

    # Only the lines of documents still open: a dispatch the session let go
    # of may have been completed meanwhile, and its lines are its own now.
    open_doc_lines = {
        row.id: row
        for row in (
            await db.scalars(
                select(DocumentLine)
                .join(Document, Document.id == DocumentLine.document_id)
                .where(
                    DocumentLine.id.in_([ln.document_line_id for ln in lines]),
                    Document.status == DocumentStatus.CONFIRMED.value,
                )
            )
        ).all()
    }
    for line in lines:
        doc_line = open_doc_lines.get(line.document_line_id)
        if (
            doc_line is not None
            and line.status in ('picked', 'short')
            and line.picked_quantity > 0
        ):
            doc_line.done_quantity = line.picked_quantity

    has_short = any(ln.status == 'short' for ln in lines)
    if direction.kind == PICKING.kind:
        await pin_picked_lots_async(db, lines)
    session.status = direction.short_status if has_short else 'completed'
    session.completed_at = datetime.now(UTC)
    await db.flush()
    await journal_session_async(db, session, session.assigned_to)
    await db.refresh(session, ['lines'])
    return session


async def undo_line_async(
    db: AsyncSession,
    direction: WmsDirection,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    user_id: UUID | None = None,
) -> WmsPickLine:
    """Undo a line the session has anything recorded on.

    The filter reads the quantity, not the status word. Picking used to ask
    for a resolved status, which stopped matching the moment a partial scan
    began leaving a pending line carrying a quantity; receiving had filtered
    on the quantity all along. The quantity is the honest source, so the
    stale copy follows the healthy one — with one case the quantity alone
    cannot see: a line somebody resolved with nothing on it. A short receive
    of zero is a recorded answer, and its row offers Undo like any other,
    so the resolved status counts as something recorded too. The same rule
    as ``rollback_session_lines_async``: the session wrote on this line, or
    it did not.

    An undo inside an open session writes no journal entry, for the reason
    a scan writes none: it moves the line's running tally, and the
    session's close records the tally that stood. Taking back the skip that
    closed the session reopens it, and that is journalled.
    """
    reopened = await _reopen_for_skipped_line_async(
        db, direction, session_id, org_id, line_id
    )
    if reopened is not None:
        # The close was journalled on each document; without this entry the
        # last word on the dispatch would be a session that is not over.
        await journal_session_async(db, reopened, user_id)
    await _get_active_session_async(db, session_id, org_id)

    line = await db.scalar(
        select(WmsPickLine)
        .where(
            WmsPickLine.id == line_id,
            WmsPickLine.session_id == session_id,
            or_(
                WmsPickLine.picked_quantity > 0,
                WmsPickLine.status != 'pending',
            ),
        )
        .with_for_update()
    )
    if not line:
        raise ServiceRejectionError('wms_nothing_to_undo')
    await _refuse_unless_line_document_open_async(db, line)

    doc_line = await db.scalar(
        select(DocumentLine).where(
            DocumentLine.id == line.document_line_id,
        )
    )
    if doc_line:
        await assert_pick_not_packed_async(db, doc_line)

    line.status = 'pending'
    line.picked_quantity = Decimal('0')
    await forget_lot_tallies_async(db, [line.id])

    if doc_line:
        doc_line.done_quantity = Decimal('0')
        doc_line.held_quantity = Decimal('0')
        doc_line.discrepancy_code = None
        doc_line.discrepancy_reason = None

    await db.flush()
    await db.refresh(line)
    return line


async def skip_line_async(
    db: AsyncSession,
    direction: WmsDirection,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
) -> WmsPickLine:
    session = await _get_active_session_async(db, session_id, org_id)

    line = await db.scalar(
        select(WmsPickLine).where(
            WmsPickLine.id == line_id,
            WmsPickLine.session_id == session_id,
            WmsPickLine.status == 'pending',
        )
    )
    if not line:
        raise ServiceRejectionError('wms_line_not_pending')

    # The guard reads the line's document line before anything is written:
    # a skip empties the tally, and a package may already hold what a
    # part-scanned line put in it. A receipt has no packages, so the guard
    # passes it by.
    doc_line = await db.scalar(
        select(DocumentLine).where(
            DocumentLine.id == line.document_line_id,
        )
    )
    await assert_pick_not_packed_async(db, doc_line, refusal='wms_skip_line_is_packed')

    line.status = 'skipped'
    line.picked_quantity = Decimal('0')
    await forget_lot_tallies_async(db, [line.id])

    if doc_line:
        doc_line.done_quantity = Decimal('0')
        doc_line.held_quantity = Decimal('0')
        # A skip is put off, not declared short, on either side: the summary
        # asks what it becomes, so nothing is written until somebody answers.
        doc_line.discrepancy_code = None
        doc_line.discrepancy_reason = None

    # skipping the last pending line ends the session; its summary can still
    # take the skip back (``_reopen_for_skipped_line_async``).
    await close_session_if_complete_async(
        db, session, short_status=direction.short_status
    )

    await db.flush()
    await db.refresh(line)
    return line


async def cancel_session_async(
    db: AsyncSession,
    direction: WmsDirection,
    session_id: UUID,
    org_id: UUID,
    user_id: UUID | None = None,
) -> None:
    """Cancel the session, which lets go of every document it holds.

    *user_id* is whoever let it go — usually the holder, or the colleague
    opening the release door on a session somebody else holds — and the
    journal names them, and names on each document the scans it dropped.
    The door holds shut while a package holds what one of its lines picked:
    the rollback would drop ``done_quantity`` under the goods already in the
    box, so that line's owner is named in the refusal instead (see
    ``rollback_session_lines_async``).
    """
    session = await _get_active_session_async(db, session_id, org_id)
    dropped = await rollback_session_lines_async(db, session_id)
    session.status = 'cancelled'
    await db.flush()
    await journal_session_async(
        db,
        session,
        user_id,
        per_document={
            doc_id: {'wms_session_discarded': scans}
            for doc_id, scans in dropped.items()
        },
    )


async def get_session_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
) -> WmsPickSession | None:
    return cast(
        WmsPickSession | None,
        await db.scalar(
            select(WmsPickSession)
            .where(
                WmsPickSession.id == session_id,
                WmsPickSession.organization_id == org_id,
            )
            .options(selectinload(WmsPickSession.lines))
        ),
    )


async def list_sessions_for_document_async(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
    *,
    inbound_only: bool,
) -> list[WmsPickSession]:
    """Sessions of one document, newest first.

    Receiving marks its sessions ``direction: inbound`` and lists only its
    own; picking never marked or filtered, and a document carries one type,
    so the flag preserves exactly that asymmetry instead of inventing a
    behaviour for either side.
    """
    query = select(WmsPickSession).where(
        session_holds_document(document_id),
        WmsPickSession.organization_id == org_id,
    )
    if inbound_only:
        query = query.where(
            WmsPickSession.meta_data['direction'].as_string() == 'inbound'
        )
    query = query.options(selectinload(WmsPickSession.lines)).order_by(
        WmsPickSession.started_at.desc()
    )
    return list((await db.scalars(query)).all())


async def load_document_async(
    db: AsyncSession, org_id: UUID, document_id: UUID, *, confirmed_only: bool
) -> Document | None:
    """The organization's document with what a session line is built from."""
    query = (
        select(Document)
        .where(
            Document.id == document_id,
            Document.organization_id == org_id,
        )
        .options(
            selectinload(Document.lines).selectinload(DocumentLine.product_template),
            selectinload(Document.lines).selectinload(DocumentLine.item),
            selectinload(Document.lines).selectinload(DocumentLine.uom),
        )
    )
    if confirmed_only:
        query = query.where(Document.status == DocumentStatus.CONFIRMED.value)
    return cast(Document | None, await db.scalar(query))


async def open_session_holding_async(
    db: AsyncSession, org_id: UUID, document_id: UUID
) -> WmsPickSession | None:
    """The active or paused session that holds the document, first or listed."""
    return cast(
        WmsPickSession | None,
        await db.scalar(
            select(WmsPickSession).where(
                session_holds_document(document_id),
                WmsPickSession.organization_id == org_id,
                WmsPickSession.status.in_(['active', 'paused']),
            )
        ),
    )


async def _finished_session_of_async(
    db: AsyncSession, direction: WmsDirection, org_id: UUID, doc: Document
) -> WmsPickSession | None:
    """The latest session over *doc*, when it ended without being cancelled."""
    latest = await db.scalar(
        select(WmsPickSession)
        .where(
            session_holds_document(doc.id),
            WmsPickSession.organization_id == org_id,
        )
        .order_by(WmsPickSession.started_at.desc())
        .limit(1)
    )
    if latest is None or latest.status not in ('completed', direction.short_status):
        return None
    if doc.confirmed_at is not None and latest.started_at < doc.confirmed_at:
        return None
    await db.refresh(latest, ['lines'])
    return cast(WmsPickSession, latest)


async def _session_meta_async(
    db: AsyncSession, direction: WmsDirection, org_id: UUID, docs: list[Document]
) -> dict[str, Any] | None:
    """The marker the direction carries, and the shelf setting as it stands now.

    The profile is read once, here: a session keeps the rule it started
    under (see ``_wms_shelf``). A transfer picked under it also keeps the
    shelf its goods are taken to, whose label ends the session.
    """
    profile = await get_profile(db, org_id)
    if profile is None or not profile.confirm_shelf_by_scan:
        return direction.session_meta
    meta = {**(direction.session_meta or {}), CONFIRM_KEY: True}
    if (
        direction.kind == PICKING.kind
        and len(docs) == 1
        and dt.is_transfer(docs[0].type)
        and docs[0].target_location_id
    ):
        meta[DESTINATION_KEY] = str(docs[0].target_location_id)
    return meta


async def start_session_async(
    db: AsyncSession,
    direction: WmsDirection,
    document_id: UUID,
    org_id: UUID,
    user_id: UUID,
    *,
    is_supported: SupportsDocType,
    line_fields: LineFields,
    sort_lines: SortLines | None = None,
) -> WmsPickSession:
    """Open a session for a CONFIRMED document, or hand back the caller's own.

    What stays with the direction is what genuinely differs: which document
    types it accepts, and what it plans on each line as the line is built
    (picking plans a group and batch and names a shelf; receiving plans
    nothing).

    A document waiting for an approval is not CONFIRMED, so it never gets
    this far: the hold is the gate. Whatever a module wants of the posting
    itself it says when the session completes the document.
    """
    await acquire_advisory_lock(db, f'{direction.lock_prefix}:{document_id}')
    doc = await load_document_async(db, org_id, document_id, confirmed_only=True)
    if not doc:
        raise ServiceRejectionError('wms_document_not_confirmed')

    if not is_supported(doc.type):
        raise ServiceRejectionError(
            'wms_document_type_not_supported', document_type=doc.type
        )

    # The session holding the document may hold others with it; the caller
    # who opened it over several dispatches gets the whole of it back.
    existing = await open_session_holding_async(db, org_id, document_id)
    # A session left behind by a closed tab used to make the document
    # unreachable: start refused because one was open, and nothing in the
    # interface could open, finish or cancel it. Handing the caller their
    # own session back is what the button already promised — the sheet reopens
    # on the lines already counted, and finishing or cancelling it works from
    # there. Someone else's session refuses, but names its holder and carries
    # the session id, so the refusal can offer the release the document
    # always needed.
    # A released session — its sheet closed, or left idle — is anybody's to
    # continue: somebody else's moves to the caller with its scans, the way
    # the take-over door moves it.
    if existing:
        if existing.assigned_to != user_id and await session_released_async(
            db, existing
        ):
            # Imported here: the access door imports this module's refusal.
            from ._wms_session_access import take_over_session_async

            await take_over_session_async(db, existing, user_id)
        if existing.assigned_to == user_id:
            mark_worked_on(existing)
            await db.refresh(existing, ['lines'])
            return existing
        holder = (
            await core_api.users.get_async(db, org_id, existing.assigned_to)
            if existing.assigned_to is not None
            else None
        )
        owner = (
            (holder.full_name if holder else None)
            or (holder.email if holder else None)
            or 'unknown'
        )
        raise SessionHeldByOtherUserError(existing.id, owner)

    # The summary that completes the document can be left by the back arrow
    # or a closed tab, and the document stays confirmed over a session that
    # already resolved every line. A new session there read 0 of N over lines
    # the document called done; the finished one comes back instead, so the
    # sheet lands on its summary and closing it books the document. Only a
    # session from the current confirmation: a document sent back to draft
    # may have changed its lines since.
    finished = await _finished_session_of_async(db, direction, org_id, doc)
    if finished is not None:
        if finished.assigned_to != user_id:
            # Imported here, as above.
            from ._wms_session_access import take_over_session_async

            await take_over_session_async(db, finished, user_id, finished=True)
        return finished

    return await open_session_async(
        db,
        direction,
        [doc],
        org_id,
        user_id,
        line_fields=line_fields,
        sort_lines=sort_lines,
    )


async def open_session_async(
    db: AsyncSession,
    direction: WmsDirection,
    docs: list[Document],
    org_id: UUID,
    user_id: UUID,
    *,
    line_fields: LineFields,
    sort_lines: SortLines | None = None,
) -> WmsPickSession:
    """Write a new session over *docs*, the first of them its ``document_id``.

    The caller has decided the documents may be picked and holds their
    locks; this writes the session, every line of each document, and — when
    there is more than one — the list of them, then lets the direction order
    the lines across all of them.
    """
    session = WmsPickSession(
        id=uuid.uuid4(),
        organization_id=org_id,
        document_id=docs[0].id,
        assigned_to=user_id,
        status='active',
        started_at=datetime.now(UTC),
        last_activity_at=datetime.now(UTC),
        meta_data=await _session_meta_async(db, direction, org_id, docs),
    )
    db.add(session)
    await db.flush()

    idx = 0
    for position, doc in enumerate(docs):
        if len(docs) > 1:
            db.add(
                WmsPickSessionDocument(
                    session_id=session.id, document_id=doc.id, position=position
                )
            )
        for line in doc.lines:
            fields = await line_fields(db, line, doc)
            planned_lot_name = fields.pop('planned_lot_name', None)
            session_line = WmsPickLine(
                id=uuid.uuid4(),
                session_id=session.id,
                document_line_id=line.id,
                pick_order=idx,
                status='pending',
                picked_quantity=Decimal('0'),
                product_name=_resolve_product_name(line),
                lot_name=_resolve_lot_name(line) or planned_lot_name,
                expected_quantity=line.expected_quantity,
                uom_symbol=_resolve_uom_symbol(line),
                **fields,
            )
            db.add(session_line)
            idx += 1

    await db.flush()
    if sort_lines is not None:
        await sort_lines(db, session.id)

    # The caller owns the commit: this is a module service, and the request
    # that called it owns the transaction. The direction bindings keep the
    # commit in their start functions, where the architecture gate has long
    # allowed it.
    return session
