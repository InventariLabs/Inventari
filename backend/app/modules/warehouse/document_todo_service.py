"""The floor's queue: what each document waits for, derived from its own rows.

To do used to be the plain document list narrowed to confirmed receipts and
dispatches, with one button each. It could not tell a document nobody had
started from one whose session was open, from one already picked and packed —
and a dispatch picked short and packed still offered *Pick*.

Nothing here adds a document status. The stage is read from what the work
already left behind:

* an open session — ``in_progress``, naming its holder, and the next action
  is to resume it;
* a finished session (or quantities recorded without one) with packages
  that cover the picked quantity — ``packed``, ready to complete;
* a finished session whose packages carry part of the pick — ``picked``,
  and the next action is to finish packing;
* a finished session with nothing in a package at all — ``picked``, and the
  next action is to complete: the warehouse does not pack this document. An
  empty box is not packing, so it changes neither the stage nor the action.
  A warehouse that never packs never sees ``packed``;
* a finished session in which every line was done in full, with nothing
  left to pack — ``ready``, and the next action is to complete (the
  hand-over for a dispatch whose packages cover the whole document). Only a
  packed dispatch gets here: a warehouse that does not pack stays at
  ``picked``. A receipt has no packing, so a receipt received in full is
  ``ready`` and one received short stays ``picked``;
* nothing recorded — ``to_start``, and the next action opens its session.

Receipts and internal receipts are the inbound list; dispatches, internal
issues and transfers are outbound. A transfer leaves shelves the way a
dispatch does, so it belongs beside them rather than in a list of its own.

Beside the two lists, To do names what is nobody's next action until somebody
answers for it — the backorder draft a short completion raised, the documents
this person can approve and the goods held in quarantine. A named batch names
itself; a receipt holds the goods it put on the quarantine shelf without one,
by a reservation owned by that receipt. Those reads are read-only; each row
sends the reader to the screen where the decision is taken.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import LotStatus, UserContextDTO
from app.core.public_api import core_api

from . import document_types as dt
from .document_query_service import list_documents, not_undone_conditions
from .models import (
    Document,
    DocumentLine,
    DocumentPackage,
    DocumentPackageLine,
    DocumentStatus,
    WmsPickSession,
    WmsPickSessionDocument,
)
from .schemas import QuarantineHoldSchema

#: Every action the queue puts on a row; the response declares the same set.
NextAction = Literal[
    'receive', 'pick', 'resume', 'pack', 'complete', 'request_approval'
]

INBOUND_TYPES: tuple[str, ...] = (dt.IN, dt.INTERNAL_IN)
OUTBOUND_TYPES: tuple[str, ...] = (dt.OUT, dt.INT, dt.INTERNAL_OUT)

#: A session in one of these is over; the document, not the session, is what
#: still waits. ``cancelled`` is not here: its scans were thrown away, so the
#: document is back at the start.
_FINISHED_SESSION_STATUSES = frozenset({'completed', 'short_pick', 'short_receive'})

#: A session still being scanned in: running, or left with its sheet closed.
#: Both hold the document against a new start — the second one is what a
#: close mid-way leaves behind — so both are work the floor walks back into.
_OPEN_SESSION_STATUSES = frozenset({'active', 'paused'})

_ZERO = Decimal('0')


def _next_action(doc: Document) -> NextAction:
    return 'receive' if dt.is_receipt(doc.type) else 'pick'


async def _holder_name_async(
    db: AsyncSession, org_id: UUID, user_id: UUID | None
) -> str | None:
    """The holder's display name, as a colleague reads it."""
    if user_id is None:
        return None
    holder = await core_api.users.get_async(db, org_id, user_id)
    if holder is None:
        return None
    return holder.full_name or holder.email or None


async def _sessions_by_document_async(
    db: AsyncSession, org_id: UUID, doc_ids: list[UUID]
) -> dict[UUID, list[WmsPickSession]]:
    """Every live or finished session touching one of these documents.

    A picking session may cover several dispatches; each of them must see the
    session, not only the one stored as its first document.
    """
    if not doc_ids:
        return {}
    rows = (
        await db.execute(
            select(WmsPickSession, WmsPickSessionDocument.document_id)
            .outerjoin(
                WmsPickSessionDocument,
                WmsPickSessionDocument.session_id == WmsPickSession.id,
            )
            .where(
                WmsPickSession.organization_id == org_id,
                WmsPickSession.status != 'cancelled',
                or_(
                    WmsPickSession.document_id.in_(doc_ids),
                    WmsPickSessionDocument.document_id.in_(doc_ids),
                ),
            )
            .order_by(WmsPickSession.started_at.asc())
        )
    ).all()
    wanted = set(doc_ids)
    by_document: dict[UUID, dict[UUID, WmsPickSession]] = defaultdict(dict)
    for session, linked_document_id in rows:
        targets = {session.document_id}
        if linked_document_id is not None:
            targets.add(linked_document_id)
        for document_id in targets & wanted:
            by_document[document_id][session.id] = session
    return {
        document_id: list(sessions.values())
        for document_id, sessions in by_document.items()
    }


async def _packing_by_document_async(
    db: AsyncSession, org_id: UUID, doc_ids: list[UUID]
) -> dict[UUID, dict[UUID, Decimal]]:
    """How much of each line stands in a package on these documents.

    A package with no lines, or with zero quantities, contributes nothing:
    an empty box is not the start of packing.
    """
    if not doc_ids:
        return {}
    rows = (
        await db.execute(
            select(
                DocumentPackage.document_id,
                DocumentPackageLine.document_line_id,
                func.sum(DocumentPackageLine.quantity),
            )
            .join(
                DocumentPackageLine,
                DocumentPackageLine.document_package_id == DocumentPackage.id,
            )
            .where(
                DocumentPackage.organization_id == org_id,
                DocumentPackage.document_id.in_(doc_ids),
            )
            .group_by(DocumentPackage.document_id, DocumentPackageLine.document_line_id)
        )
    ).all()
    packed: dict[UUID, dict[UUID, Decimal]] = defaultdict(dict)
    for document_id, line_id, quantity in rows:
        if quantity is None or quantity <= _ZERO:
            continue
        packed[document_id][line_id] = quantity
    return packed


def _packed_covers_pick(doc: Document, packed: dict[UUID, Decimal]) -> bool:
    """Whether every picked line stands in a package in full.

    A document with packages but nothing picked has not covered anything: the
    work is still to pick it.
    """
    picked = [line for line in doc.lines if (line.done_quantity or _ZERO) > 0]
    if not picked:
        return False
    return all(
        packed.get(line.id, _ZERO) >= (line.done_quantity or _ZERO) for line in picked
    )


def _done_in_full(doc: Document) -> bool:
    """Whether no line is short: every line has at least what was planned."""
    return all(
        (line.done_quantity or _ZERO) >= line.expected_quantity for line in doc.lines
    )


async def work_stage_updates_async(
    db: AsyncSession,
    org_id: UUID,
    documents: list[Document],
    *,
    approvals_enabled: bool = False,
) -> dict[UUID, dict[str, Any]]:
    """The stage, next action and holder each document's row should carry.

    Returned as schema field updates rather than written onto the ORM rows: the
    fields are transient (``DocumentSchema`` publishes them with a ``None``
    default) and Pydantic's ``from_attributes`` has no column to read them from,
    so the row is built once, here, and copied with the answer.

    With ``approvals_enabled``, a row about to be started whose rule now asks
    for an approval and has none carries ``request_approval`` instead: the
    queue must not promise a session the gate will refuse.
    """
    if not documents:
        return {}
    doc_ids = [doc.id for doc in documents]
    sessions_by_document = await _sessions_by_document_async(db, org_id, doc_ids)
    packed_by_document = await _packing_by_document_async(db, org_id, doc_ids)

    updates: dict[UUID, dict[str, Any]] = {}
    holder_names: dict[UUID, str | None] = {}
    for doc in documents:
        sessions = sessions_by_document.get(doc.id, [])
        open_sessions = [
            session for session in sessions if session.status in _OPEN_SESSION_STATUSES
        ]
        if open_sessions:
            holder_id = open_sessions[-1].assigned_to
            if holder_id is not None and holder_id not in holder_names:
                holder_names[holder_id] = await _holder_name_async(
                    db, org_id, holder_id
                )
            updates[doc.id] = {
                'work_stage': 'in_progress',
                'next_action': 'resume',
                'stage_holder_name': (
                    holder_names.get(holder_id) if holder_id is not None else None
                ),
            }
            continue

        recorded = any(
            session.status in _FINISHED_SESSION_STATUSES for session in sessions
        ) or any((line.done_quantity or _ZERO) > 0 for line in doc.lines)
        if not recorded:
            updates[doc.id] = {
                'work_stage': 'to_start',
                'next_action': _next_action(doc),
                'stage_holder_name': None,
            }
            continue

        packed = packed_by_document.get(doc.id, {})
        covered = _packed_covers_pick(doc, packed)
        # Nothing in a package means the warehouse does not pack this
        # document, so completing is the only step left. A box without lines
        # leaves ``packed`` empty too: it is not the start of packing.
        stage = 'packed' if covered else 'picked'
        if _done_in_full(doc) and (covered or dt.is_receipt(doc.type)):
            stage = 'ready'
        updates[doc.id] = {
            'work_stage': stage,
            'next_action': 'pack' if packed and not covered else 'complete',
            'stage_holder_name': None,
        }

    # A document confirmed before the rule reached it is still waiting to be
    # started, but the taking session would refuse it: its next action is the
    # request that sends it back for a signature, not the pick the row used
    # to promise. Only rows about to start are asked about — one already under
    # way got past the gate when it opened.
    starting = [
        doc
        for doc in documents
        if updates.get(doc.id, {}).get('next_action') in ('receive', 'pick')
    ]
    if starting and approvals_enabled:
        needs_approval = await _documents_needing_approval_async(db, org_id, starting)
        for doc in starting:
            if doc.id in needs_approval:
                updates[doc.id] = {
                    **updates[doc.id],
                    'next_action': 'request_approval',
                }
    return updates


async def _documents_needing_approval_async(
    db: AsyncSession, org_id: UUID, documents: list[Document]
) -> set[UUID]:
    """Which of these documents the approval rule covers, by its one answer.

    The approvals module owns the rule; this asks it about a page at once,
    naming each document with the person who confirmed it. An installation
    without the package has no rule, and nothing here needs a signature.
    """
    try:
        from app.modules.approvals.approvals_api import approvals_api
    except ModuleNotFoundError:
        return set()
    return await approvals_api.documents_needing_approval_async(
        db, org_id, [(doc.id, doc.confirmed_by) for doc in documents]
    )


async def todo_documents_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    date_to: date,
    limit: int,
    inbound_offset: int = 0,
    outbound_offset: int = 0,
    approvals_enabled: bool = False,
    location_ids: list[UUID] | None = None,
) -> tuple[list[Document], int, list[Document], int, dict[UUID, dict[str, Any]]]:
    """The two lists of the floor's queue, each with its own server total.

    ``location_ids`` keeps the documents that go to or come from one of those
    places, the way the document list does.

    Each side pages on its own offset: the lists have different lengths, so a
    shared offset would skip rows on the shorter one.
    """
    end_of_day = datetime.combine(date_to, time(23, 59, 59))
    inbound, inbound_total = await list_documents(
        db,
        org_id,
        doc_type=','.join(INBOUND_TYPES),
        status=DocumentStatus.CONFIRMED.value,
        date_to=end_of_day,
        limit=limit,
        offset=inbound_offset,
        location_ids=location_ids,
        sort_by='document_date',
        sort_order='asc',
    )
    outbound, outbound_total = await list_documents(
        db,
        org_id,
        doc_type=','.join(OUTBOUND_TYPES),
        status=DocumentStatus.CONFIRMED.value,
        date_to=end_of_day,
        limit=limit,
        offset=outbound_offset,
        location_ids=location_ids,
        sort_by='document_date',
        sort_order='asc',
    )
    stage_updates = await work_stage_updates_async(
        db,
        org_id,
        [*inbound, *outbound],
        approvals_enabled=approvals_enabled,
    )
    return inbound, inbound_total, outbound, outbound_total, stage_updates


async def completed_documents_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    since: datetime,
    limit: int,
    location_ids: list[UUID] | None = None,
) -> tuple[list[Document], int]:
    """Receipts and dispatches posted since ``since``, newest first.

    The work that was done, for the part of To do that shows it: nothing here
    is asked of anybody any more.
    """
    return await list_documents(
        db,
        org_id,
        doc_type=','.join((*INBOUND_TYPES, *OUTBOUND_TYPES)),
        status=DocumentStatus.COMPLETED.value,
        completed_from=since,
        location_ids=location_ids,
        limit=limit,
        # Newest posted first, by the time the card prints: ordered by when
        # it was typed in, an order written last week and dispatched a minute
        # ago was the card a short column left out.
        sort_by='completed_at',
        sort_order='desc',
        # A done task names its document and counts its lines
        # (``line_tallies_async``); no line is read for it.
        lines='none',
        # An undone document and the reversal that undid it are one piece of
        # work that came to nothing, not two things done.
        extra_conditions=not_undone_conditions(),
    )


async def line_tallies_async(
    db: AsyncSession, document_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    """Per document: how many lines it has, and how many were done in full.

    What a task card counts, counted in the database: a day's posted
    documents carried thousands of lines into memory to be counted.
    """
    if not document_ids:
        return {}
    rows = await db.execute(
        select(
            DocumentLine.document_id,
            func.count(DocumentLine.id),
            func.count(DocumentLine.id).filter(
                func.coalesce(DocumentLine.done_quantity, 0)
                >= DocumentLine.expected_quantity
            ),
        )
        .where(DocumentLine.document_id.in_(document_ids))
        .group_by(DocumentLine.document_id)
    )
    return {document_id: (lines, done) for document_id, lines, done in rows.all()}


async def backorder_drafts_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    location_ids: list[UUID] | None = None,
) -> tuple[list[Document], int]:
    """The drafts a short completion raised, oldest first.

    A draft waits on somebody to confirm it (the goods are still owed) or
    cancel it (they are not). Only the documents the application raised are
    here: a draft a person typed has no ``backorder_id`` and is their own
    business until they issue it. Each row carries the number of the
    document it continues, so the reader knows which order is short.
    """
    drafts, total = await list_documents(
        db,
        org_id,
        status=DocumentStatus.DRAFT.value,
        backorder_only=True,
        location_ids=location_ids,
        limit=limit,
        sort_by='created_at',
        sort_order='asc',
    )
    origin_ids = [draft.backorder_id for draft in drafts if draft.backorder_id]
    if origin_ids:
        rows = (
            await db.execute(
                select(Document.id, Document.number).where(
                    Document.organization_id == org_id,
                    Document.id.in_(origin_ids),
                )
            )
        ).all()
        numbers: dict[UUID, str] = {row[0]: row[1] for row in rows}
        for draft in drafts:
            if draft.backorder_id is not None:
                cast(Any, draft).backorder_of_number = numbers.get(draft.backorder_id)
    return drafts, total


async def awaiting_approval_documents_async(
    db: AsyncSession,
    org_id: UUID,
    user: UserContextDTO,
    *,
    limit: int,
    offset: int = 0,
    location_ids: list[UUID] | None = None,
) -> tuple[list[Document], int]:
    """The documents this person can approve or reject, newest first.

    Same rule as the approvals queue: the approvals module must be on, the
    reader must hold ``approvals:approve`` and the request's open stage must
    name them. A request parked where nobody can decide it is not a decision
    this person can take, so it stays out of the block. A switched-off module
    is answered here, before the lookup; anything the lookup raises is a
    defect and travels as one, because an empty list would tell the approver
    there is nothing to decide.
    """
    if not await core_api.organizations.is_module_enabled_async(
        db, org_id, 'approvals'
    ):
        return [], 0
    if not user.has_permission('approvals:approve'):
        return [], 0
    # Imported only once the module is known to be on: the warehouse loads
    # without the approvals package.
    from app.modules.approvals.approvals_api import approvals_api

    requests = await approvals_api.list_requests(
        db,
        org_id,
        target_type='document',
        pending_for_user_id=user.id,
    )

    target_ids = [request.target_id for request in requests]
    if not target_ids:
        return [], 0
    return await list_documents(
        db,
        org_id,
        target_ids=target_ids,
        location_ids=location_ids,
        limit=limit,
        offset=offset,
        sort_by='created_at',
        sort_order='desc',
    )


async def _receipt_quarantine_holds_async(
    db: AsyncSession, org_id: UUID, *, limit: int
) -> tuple[list[QuarantineHoldSchema], int]:
    """The goods a completed receipt holds on the quarantine shelf.

    A line held back without a batch has no lot to carry the hold, so the
    receipt keeps a reservation on the goods instead. The outstanding rows —
    what a transfer or a scrap has not released yet — are the holds, summed
    per receipt and product, and named by the receipt that placed them.
    """
    held_receipt_ids = list(
        (
            await db.scalars(
                select(Document.id)
                .join(DocumentLine, DocumentLine.document_id == Document.id)
                .where(
                    Document.organization_id == org_id,
                    Document.status == DocumentStatus.COMPLETED.value,
                    DocumentLine.held_quantity > 0,
                )
                .distinct()
            )
        ).all()
    )
    if not held_receipt_ids:
        return [], 0
    # The stock side of the hold — the group, its sum, the product, its unit
    # and the shelf — is one read through the contract; the document's own
    # number and date stay here, because the document table is the module's.
    holds = await core_api.queries.get_reservations_held_by_documents_async(
        db, org_id, held_receipt_ids
    )
    total = len(holds)
    if not holds:
        return [], 0

    receipt_rows = (
        await db.execute(
            select(Document.id, Document.number, Document.created_at).where(
                Document.id.in_({hold.document_id for hold in holds})
            )
        )
    ).all()
    receipts = {row.id: row for row in receipt_rows}
    holds.sort(
        key=lambda hold: (
            receipts[hold.document_id].created_at,
            receipts[hold.document_id].number,
            hold.product_name or '',
        )
    )
    rows = holds[:limit]
    if not rows:
        return [], total

    receipt_ids = {row.document_id for row in rows}
    reasons: dict[tuple[UUID, UUID], str | None] = {}
    reason_rows = (
        await db.execute(
            select(
                DocumentLine.document_id,
                DocumentLine.product_template_id,
                DocumentLine.discrepancy_reason,
                DocumentLine.discrepancy_code,
            ).where(
                DocumentLine.document_id.in_(receipt_ids),
                DocumentLine.held_quantity > 0,
            )
        )
    ).all()
    for document_id, template_id, reason, code in reason_rows:
        if template_id is None:
            continue
        reasons.setdefault((document_id, template_id), reason or code)

    # The record the held goods stand in, so the release form opens on the
    # goods instead of asking the reader to find them: the stock search
    # hides a shelf whose stock is fully reserved, and these goods are
    # reserved by the receipt being released.
    item_by_group: dict[tuple[UUID, UUID], UUID] = {}
    grouped_items = await core_api.items.list_with_template_async(
        db,
        org_id,
        sorted({row.product_template_id for row in rows}),
    )
    shelf_ids = {row.location_id for row in rows}
    records = [
        item
        for items in grouped_items.values()
        for item in items
        if item.lot_id is None and item.location_id in shelf_ids
    ]
    records.sort(key=lambda item: (-(item.quantity or _ZERO), item.created_at))
    for item in records:
        if item.template_id is None:
            continue
        item_by_group.setdefault((item.template_id, item.location_id), item.id)

    return [
        QuarantineHoldSchema(
            document_id=row.document_id,
            document_number=receipts[row.document_id].number,
            name=receipts[row.document_id].number,
            product_template_id=row.product_template_id,
            item_id=item_by_group.get((row.product_template_id, row.location_id)),
            product_name=row.product_name,
            quantity=row.quantity or _ZERO,
            uom_symbol=row.uom_symbol,
            reason=reasons.get((row.document_id, row.product_template_id)),
            location_id=row.location_id,
            location_name=row.location_name,
        )
        for row in rows
    ], total


async def quarantine_holds_async(
    db: AsyncSession, org_id: UUID, *, limit: int
) -> tuple[list[QuarantineHoldSchema], int]:
    """The goods held back, with what is left of each and why it is held.

    A named batch is released on the batch's own screen; goods held without
    one are named by the receipt that placed them, and their release or
    write-off is a transfer or a scrap off the quarantine shelf. Rows come
    from the same reads as those screens, so the numbers agree.
    """
    lots, lots_total = await core_api.stock.list_lot_rows_async(
        db,
        org_id,
        status=LotStatus.QUARANTINED.value,
        limit=limit,
    )
    receipt_holds, receipt_total = await _receipt_quarantine_holds_async(
        db, org_id, limit=limit
    )
    return [
        QuarantineHoldSchema(
            lot_id=lot.id,
            name=lot.name,
            product_name=lot.product_name,
            quantity=lot.on_hand,
            uom_symbol=lot.uom_symbol,
            reason=lot.status_reason,
        )
        for lot in lots
    ] + receipt_holds, lots_total + receipt_total
