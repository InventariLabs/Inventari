"""Closing a WMS session — the one rule both directions answer to.

Picking and receiving run on the same two tables and differ only in the name
of their short-terminal status. The frontend flips to its own "completed"
summary as soon as the last line resolves and has never called the explicit
complete endpoint, so an ``active`` session left behind blocks the document
from ever completing or being cancelled. Receiving learned that the hard way;
picking carried the same defect until this module gave both the same answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._stock_executor_helpers import line_source_shelf
from ._wms_direction import PICKING
from ._wms_line_utils import document_lines_by_id_async, session_document_ids_async
from .document_line_split import insert_sibling_lines_async
from .document_value_service import compute_line_values
from .models import (
    Document,
    DocumentLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickLineLot,
    WmsPickSession,
)
from .packing_service import assert_pick_not_packed_async

RESOLVED_STATUSES = ('picked', 'short', 'skipped')

#: Session ``meta_data`` keys of a transfer that confirms its destination by
#: scan: the shelf the goods are taken to, and the mark that its label was read.
DESTINATION_KEY = 'destination_shelf_id'
DESTINATION_SCANNED_KEY = 'destination_scanned'


def destination_to_scan(session: WmsPickSession) -> UUID | None:
    """The destination shelf of a transfer whose label was not read yet."""
    meta = session.meta_data or {}
    raw = meta.get(DESTINATION_KEY)
    if not raw or meta.get(DESTINATION_SCANNED_KEY):
        return None
    return UUID(raw)


def destination_awaited(
    session: WmsPickSession, lines: Sequence[WmsPickLine]
) -> UUID | None:
    """The shelf whose label still has to be scanned before the session ends.

    Only once the lines are answered and something was actually taken: a
    transfer in which nothing moved has no destination to confirm.
    """
    destination = destination_to_scan(session)
    if destination is None:
        return None
    if any(ln.status not in RESOLVED_STATUSES for ln in lines):
        return None
    if not any(ln.picked_quantity > 0 for ln in lines):
        return None
    return destination


async def lot_covers_async(
    db: AsyncSession,
    doc: Document,
    doc_line: DocumentLine,
    template_id: UUID,
    lot_id: UUID,
    quantity: Decimal,
) -> bool:
    """Whether *lot_id* alone can give *quantity* (in the line's unit) at the line's shelf.

    What the document itself holds counts as available to it; what other
    documents hold does not. What the document's other lines already take
    from the batch is not available to this one.
    """
    stock_quantity = await core_api.uoms.to_stock_uom_async(
        db, doc.organization_id, template_id, quantity, doc_line.uom_id
    )
    stock_quantity += await _taken_by_other_lines_async(
        db, doc, doc_line, template_id, lot_id
    )
    shelf = line_source_shelf(
        doc_line,
        doc,
        None
        if doc_line.source_location_id is not None or doc.source_location_id is not None
        else doc_line.item,
    )
    draw = await core_api.stock.plan_draw_async(
        db,
        doc.organization_id,
        template_id,
        shelf,
        stock_quantity,
        lot_id=lot_id,
        any_owner=True,
        except_document_id=doc.id,
    )
    return sum((taken.consumed for taken in draw), Decimal('0')) >= stock_quantity


async def lot_tallies_async(
    db: AsyncSession, pick_line_id: UUID
) -> list[WmsPickLineLot]:
    """What the pick line took from each batch, in the order it was first scanned."""
    return list(
        (
            await db.scalars(
                select(WmsPickLineLot)
                .where(WmsPickLineLot.pick_line_id == pick_line_id)
                .order_by(WmsPickLineLot.position)
            )
        ).all()
    )


async def tally_lot_async(
    db: AsyncSession, line: WmsPickLine, lot_id: UUID, lot_name: str, quantity: Decimal
) -> None:
    """Add *quantity* to what the line took from *lot_id*."""
    tallies = await lot_tallies_async(db, line.id)
    for tally in tallies:
        if tally.lot_id == lot_id:
            tally.quantity += quantity
            return
    db.add(
        WmsPickLineLot(
            pick_line_id=line.id,
            lot_id=lot_id,
            lot_name=lot_name,
            quantity=quantity,
            position=len(tallies),
        )
    )


async def forget_lot_tallies_async(
    db: AsyncSession, pick_line_ids: Sequence[UUID]
) -> None:
    """Drop what the lines took from each batch, with the quantity they undo."""
    if pick_line_ids:
        await db.execute(
            delete(WmsPickLineLot).where(WmsPickLineLot.pick_line_id.in_(pick_line_ids))
        )


async def _taken_by_other_lines_async(
    db: AsyncSession,
    doc: Document,
    doc_line: DocumentLine,
    template_id: UUID,
    lot_id: UUID,
) -> Decimal:
    """What the open sessions' other lines of the document take from *lot_id*.

    A line still being picked from the batch takes what it expects (less
    what it took from other batches), a resolved one what it picked from it:
    two lines of one product cannot both be given a batch that has stock for
    one of them.
    """
    await db.flush()
    rows = (
        await db.execute(
            select(WmsPickLine, DocumentLine.uom_id)
            .join(WmsPickSession, WmsPickSession.id == WmsPickLine.session_id)
            .join(DocumentLine, DocumentLine.id == WmsPickLine.document_line_id)
            .where(
                DocumentLine.document_id == doc.id,
                WmsPickSession.status.in_(('active', 'paused')),
                WmsPickLine.document_line_id != doc_line.id,
            )
        )
    ).all()
    taken = Decimal('0')
    for pick_line, uom_id in rows:
        tallies = await lot_tallies_async(db, pick_line.id)
        here = sum((t.quantity for t in tallies if t.lot_id == lot_id), Decimal('0'))
        elsewhere = sum(
            (t.quantity for t in tallies if t.lot_id != lot_id), Decimal('0')
        )
        quantity = here
        if pick_line.lot_id == lot_id:
            quantity = (
                pick_line.expected_quantity
                if pick_line.status == 'pending'
                else pick_line.picked_quantity
            ) - elsewhere
        if quantity <= 0:
            continue
        taken += await core_api.uoms.to_stock_uom_async(
            db, doc.organization_id, template_id, quantity, uom_id
        )
    return taken


async def _lots_picked_async(
    db: AsyncSession, line: WmsPickLine
) -> list[tuple[UUID, str, Decimal]]:
    """The batches the line ended up taking from, and how much from each.

    The scans tallied what they took. The line's final total can differ --
    counted rather than scanned, or lowered by a count that supersedes the
    scans -- so the tallies are made to add up to it: a surplus belongs to the
    batch the line stood on, a deficit comes off the last batches scanned. A
    line that never named a batch has none, and the strategy serves it.
    """
    parts = [
        (t.lot_id, t.lot_name, t.quantity) for t in await lot_tallies_async(db, line.id)
    ]
    surplus = line.picked_quantity - sum((q for _, _, q in parts), Decimal('0'))
    if surplus > 0 and line.lot_id is not None and line.lot_name:
        for index, (lot_id, name, quantity) in enumerate(parts):
            if lot_id == line.lot_id:
                parts[index] = (lot_id, name, quantity + surplus)
                break
        else:
            parts.append((line.lot_id, line.lot_name, surplus))
    while surplus < 0 and parts:
        lot_id, name, quantity = parts[-1]
        cut = min(quantity, -surplus)
        parts[-1] = (lot_id, name, quantity - cut)
        surplus += cut
        if parts[-1][2] <= 0:
            parts.pop()
    return [part for part in parts if part[2] > 0]


async def _split_document_line_async(
    db: AsyncSession,
    doc: Document,
    doc_line: DocumentLine,
    parts: list[tuple[UUID, str, Decimal]],
) -> None:
    """Write the document line once per batch it was picked from.

    The line keeps the first batch and what is still to pick; each other
    batch becomes a line of its own, picked in full -- the shape of one order
    line served by several batches. Their rows follow the line, so the
    numbers of the document stay in order.
    """
    first_quantity = parts[0][2]
    others = parts[1:]
    taken_elsewhere = sum((q for _, _, q in others), Decimal('0'))
    doc_line.batch_number = parts[0][1]
    doc_line.done_quantity = first_quantity
    doc_line.quantity -= taken_elsewhere
    doc_line.expected_quantity -= taken_elsewhere
    compute_line_values(doc_line)

    await insert_sibling_lines_async(
        db,
        doc,
        doc_line,
        [
            {
                'quantity': quantity,
                'expected_quantity': quantity,
                'done_quantity': quantity,
                'batch_number': name,
            }
            for _, name, quantity in others
        ],
    )


async def pin_picked_lots_async(db: AsyncSession, lines: Sequence[WmsPickLine]) -> None:
    """Make the document name the batches the picker took.

    Completing the document draws by the batch its line names and, where the
    line names none, by the product's strategy over every active batch --
    whatever was physically picked. A pick line that stood for a batch
    (planned, or the one a scan named) hands it to the document line, so the
    books lose the batch that left the shelf. A line picked from several
    batches is split into one document line per batch, so the books name each
    of them.

    A line the document itself pinned to a batch keeps it. A line that holds
    a batch holds it to the end: planning names a batch only when it alone
    covers the line and every scan checks that, so a batch that cannot cover
    what was picked from it here went off since -- quarantined, or drawn by
    another document. The closing is refused then, rather than left to the
    strategy to book another batch than the one that left the shelf.
    """
    for line in lines:
        if line.status not in ('picked', 'short') or line.picked_quantity <= 0:
            continue
        parts = await _lots_picked_async(db, line)
        if not parts:
            continue
        doc_line = await db.get(DocumentLine, line.document_line_id)
        # the line's own document: a session over several dispatches holds
        # lines of each.
        doc = await db.get(Document, doc_line.document_id) if doc_line else None
        template_id = doc_line.product_template_id if doc_line else None
        if (
            doc is None
            or doc_line is None
            or template_id is None
            or doc_line.batch_number
            or doc_line.serial_number
        ):
            continue
        for lot_id, lot_name, quantity in parts:
            if not await lot_covers_async(
                db, doc, doc_line, template_id, lot_id, quantity
            ):
                raise ServiceRejectionError(
                    'picking_lot_no_longer_available',
                    lot=lot_name,
                    quantity=format(quantity.normalize(), 'f'),
                )
        if len(parts) == 1:
            doc_line.batch_number = parts[0][1]
        else:
            await _split_document_line_async(db, doc, doc_line, parts)


async def journal_session_async(
    db: AsyncSession,
    session: WmsPickSession,
    user_id: UUID | None,
    docs: list[Document] | None = None,
    extra: dict[str, Any] | None = None,
    per_document: dict[UUID, dict[str, Any]] | None = None,
) -> None:
    """One journal entry per document of the session, saying what it now is.

    Written when a session closes and when it is cancelled — the acts that
    decide whether a document can be completed — and when one opens over
    several dispatches, which is the only record that they were picked
    together. The single scans in between
    are not journaled: each one moves a line's tally, and the document's
    completion records the tally that stood.

    *docs* is the session's documents when the caller has them in hand —
    the start does — and they are read otherwise. *extra* is what the act
    adds to every entry's snapshot: a handover names both people there.
    *per_document* adds to one document's entry only: a discard names, on
    each dispatch, the scans that dispatch lost.
    """
    if docs is not None:
        document_ids = [doc.id for doc in docs]
        numbers = {doc.id: doc.number for doc in docs}
    else:
        document_ids = await session_document_ids_async(db, session)
        rows = await db.execute(
            select(Document.id, Document.number).where(Document.id.in_(document_ids))
        )
        numbers = dict(rows.tuples().all())
    together = [numbers[doc_id] for doc_id in document_ids if doc_id in numbers]
    for doc_id in document_ids:
        if doc_id not in numbers:
            continue
        snapshot: dict[str, Any] = {
            'number': numbers[doc_id],
            'wms_session_id': str(session.id),
            'wms_session_status': session.status,
        }
        if len(together) > 1:
            snapshot['picked_together'] = together
        if extra:
            snapshot.update(extra)
        if per_document and doc_id in per_document:
            snapshot.update(per_document[doc_id])
        await core_api.audit_log.log_action_async(
            db,
            organization_id=session.organization_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.DOCUMENT,
            target_id=doc_id,
            snapshot=snapshot,
        )


async def document_lines_resolved_async(
    db: AsyncSession, session_id: UUID, document_id: UUID
) -> bool:
    """Whether every line the session holds for *document_id* is resolved.

    A session over several dispatches resolves them one at a time: a
    dispatch whose lines are all answered is done with the session and may
    be completed, while the session goes on for the others. A document the
    session holds no line of is not resolved — the empty session's rule.
    """
    statuses = (
        await db.scalars(
            select(WmsPickLine.status)
            .join(DocumentLine, DocumentLine.id == WmsPickLine.document_line_id)
            .where(
                WmsPickLine.session_id == session_id,
                DocumentLine.document_id == document_id,
            )
        )
    ).all()
    return bool(statuses) and all(st in RESOLVED_STATUSES for st in statuses)


async def close_session_if_complete_async(
    db: AsyncSession,
    session: WmsPickSession,
    *,
    short_status: Literal['short_pick', 'short_receive'],
) -> None:
    """Mark the session terminal once every line is resolved."""
    lines = (
        await db.scalars(
            select(WmsPickLine)
            .where(WmsPickLine.session_id == session.id)
            .with_for_update()
        )
    ).all()
    if not lines or not all(ln.status in RESOLVED_STATUSES for ln in lines):
        return
    # a transfer that confirms its destination ends with that scan.
    if destination_awaited(session, lines) is not None:
        return
    has_short = any(ln.status == 'short' for ln in lines)
    if short_status == PICKING.short_status:
        # while the session is still open: the lines' claims on a batch are
        # read from it.
        await pin_picked_lots_async(db, lines)
    session.status = short_status if has_short else 'completed'
    session.completed_at = datetime.now(UTC)
    await db.flush()
    await journal_session_async(db, session, session.assigned_to)


async def rollback_session_lines_async(
    db: AsyncSession, session_id: UUID
) -> dict[UUID, list[str]]:
    """Undo everything a session wrote, so cancelling leaves no orphan quantity.

    A line scanned part-way stays ``pending`` with a quantity on it, and a
    skipped line writes a discrepancy code. Filtering on the resolved statuses
    alone left both behind: the document went on showing a receipt that no
    finished session had made, and nothing on it said who had put it there. A
    cancelled session is a session that did not happen, so every line it wrote
    goes back — and only those, because a line it never touched may carry a
    quantity from an earlier session. A document the session already let go
    of, and that was completed or cancelled since, keeps its lines: they are
    that document's record now, not the session's.

    What a package already holds does not go back with the rest: the goods
    are in a box, and dropping ``done_quantity`` under them would leave the
    box saying more left than the dispatch ships until completion found out.
    Every line is checked before any of them is put back, so the refusal
    names the packed line whether it stands first or last and leaves the
    session exactly as it was.

    Returns what was dropped, per document, as ``"<product>: <quantity>"``
    for every line that had something scanned, so the journal can say what a
    discard cost.
    """
    touched = (
        await db.scalars(
            select(WmsPickLine)
            .join(DocumentLine, DocumentLine.id == WmsPickLine.document_line_id)
            .join(Document, Document.id == DocumentLine.document_id)
            .where(
                WmsPickLine.session_id == session_id,
                Document.status == DocumentStatus.CONFIRMED.value,
                or_(
                    WmsPickLine.status != 'pending',
                    WmsPickLine.picked_quantity > 0,
                ),
            )
            .with_for_update(of=WmsPickLine)
        )
    ).all()

    # The document line beside each touched line, read once: the guard below
    # and the reset over the same pairs, with no second round of queries
    # between them.
    doc_lines = await document_lines_by_id_async(
        db, [line.document_line_id for line in touched]
    )
    pairs: list[tuple[WmsPickLine, DocumentLine | None]] = [
        (line, doc_lines.get(line.document_line_id)) for line in touched
    ]

    for _, doc_line in pairs:
        await assert_pick_not_packed_async(
            db, doc_line, refusal='wms_cancel_session_is_packed'
        )

    dropped: dict[UUID, list[str]] = {}
    for line, doc_line in pairs:
        if doc_line:
            if line.picked_quantity > 0:
                dropped.setdefault(doc_line.document_id, []).append(
                    f'{doc_line.name}: {line.picked_quantity.normalize():f}'
                )
            doc_line.done_quantity = Decimal('0')
            doc_line.held_quantity = Decimal('0')
            doc_line.discrepancy_code = None
            doc_line.discrepancy_reason = None

        line.status = 'pending'
        line.picked_quantity = Decimal('0')
    await forget_lot_tallies_async(db, [line.id for line in touched])
    return dropped
