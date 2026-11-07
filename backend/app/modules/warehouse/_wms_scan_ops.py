"""The scan rule both WMS directions answer to.

Picking and receiving match a scan differently — picking by barcode,
receiving with the already-received answer and the line's own barcode —
but once a line is matched the rule is one: refuse when the
document left CONFIRMED, answer a quantity past the line's own figure, write
the counted quantity on the session line and the document line, close the
session when the last line resolves. That rule was copied per direction and
drifted with the vocabulary; it lives here once, parameterised by
``WmsDirection``.

What past the figure means depends on the policy handed in. Picking refuses
it, as it always has. Receiving (``may_exceed_over_receipt`` is not None)
allows it within the organization's over-receipt tolerance, and past that
only for a holder of the over-receipt permission — the same gate the office
doors ask (see ``_over_receipt``). A surplus line carries its reason code
either way.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockLotDTO
from app.core.public_api import core_api

from ._over_receipt import SURPLUS_CODE, is_surplus
from ._po_receipt_guard import assert_line_over_receipt_allowed_async
from ._wms_direction import WmsDirection
from ._wms_session_close import (
    close_session_if_complete_async,
    destination_awaited,
    lot_covers_async,
    lot_tallies_async,
    tally_lot_async,
)
from .models import Document, DocumentLine, DocumentStatus, WmsPickLine, WmsPickSession


def scan_response(
    direction: WmsDirection,
    status: str,
    *,
    line_id: UUID | None = None,
    product_name: str | None = None,
    quantity: float = 0,
    expected_quantity: float = 0,
    uom_symbol: str | None = None,
    bin_location: str | None = None,
    lot_name: str | None = None,
    planned_lot_name: str | None = None,
    expiry_date: date | None = None,
    shelf: str | None = None,
    shelf_id: UUID | None = None,
    session_complete: bool = False,
    message: str = '',
) -> dict[str, Any]:
    """The scan envelope, under the direction's name for the quantity.

    Each router reads these dicts through its own response model, which
    keeps only the fields its direction declares — receiving's schema has no
    ``bin_location`` and simply ignores it here.
    """
    return {
        'status': status,
        'line_id': str(line_id) if line_id else None,
        'product_name': product_name,
        direction.quantity_key: quantity,
        'expected_quantity': expected_quantity,
        'uom_symbol': uom_symbol,
        'bin_location': bin_location,
        'lot_name': lot_name,
        'planned_lot_name': planned_lot_name,
        'expiry_date': expiry_date,
        'shelf': shelf,
        'shelf_id': str(shelf_id) if shelf_id else None,
        'session_complete': session_complete,
        'message': message,
    }


async def _lot_the_scan_names_async(
    db: AsyncSession,
    org_id: UUID,
    line: WmsPickLine,
    doc_line: DocumentLine | None,
    template_id: UUID,
    lot_code: str,
    *,
    unnamed_quantity: Decimal,
) -> tuple[bool, StockLotDTO | None]:
    """Check the lot code a scan read off the label against the line's lot.

    Returns ``(accepted, adopted)``. A code that is the line's lot passes
    with *adopted* None. Another lot of the same product is the lot that is
    physically leaving: it comes back as *adopted* for the caller to put on
    the line once the scan is accepted, so completion books what was picked.
    A code no lot of the product answers to, any other lot where the
    document itself names the batch, or any lot once some of the quantity
    picked on the line names none (the strategy served it), is refused -- a
    quantity picked from no batch cannot be relabelled. Once the quantity
    picked is all accounted for by batches, another batch is the next one
    the line is picked from, and completion books each.
    """
    code = lot_code.strip().casefold()
    if not code or code == (line.lot_name or '').casefold():
        return True, None
    if doc_line is not None and (doc_line.batch_number or doc_line.serial_number):
        return False, None
    if unnamed_quantity > 0:
        return False, None
    lots = await core_api.stock.list_lots_async(db, org_id, template_id)
    named = next((lot for lot in lots if lot.name.casefold() == code), None)
    return named is not None, named


async def execute_scan_async(
    db: AsyncSession,
    direction: WmsDirection,
    session: WmsPickSession,
    line: WmsPickLine,
    quantity: Decimal,
    *,
    template_id: UUID | None = None,
    lot_code: str | None = None,
    may_exceed_over_receipt: bool | None = None,
) -> dict[str, Any]:
    """Apply one matched scan to its line, and answer what happened.

    *may_exceed_over_receipt* is receiving's policy switch: ``None`` keeps
    the plain over-quantity refusal picking has always had, ``False``/``True``
    allow the over-receipt tolerance and say whether the caller holds the
    permission to go past it. *lot_code* is the batch the picker read off the
    label, checked against the line's own; it needs *template_id*, the product
    the scan resolved to.
    """
    doc_line = await db.scalar(
        select(DocumentLine).where(
            DocumentLine.id == line.document_line_id,
        )
    )

    # Reject scan if the line's document is no longer CONFIRMED
    # (completed/cancelled). The line's own document, not the session's
    # first: a session over several dispatches goes on after one of them
    # was completed, and its others are still to be picked.
    doc = await db.scalar(
        select(Document)
        .where(
            Document.id == (doc_line.document_id if doc_line else session.document_id)
        )
        .with_for_update()
    )
    if doc and doc.status != DocumentStatus.CONFIRMED.value:
        return scan_response(
            direction,
            'rejected',
            message=f'Cannot {direction.verb}: document is {doc.status}',
        )

    # The caller matched this line before the document lock was taken, so
    # what it holds is the snapshot from before every competitor this lock
    # waited for — a parallel scan, a short, an undo. The plain identity map
    # would hand that same stale object back on any re-select, so the row is
    # re-read under its own lock with the map refreshed: the arithmetic and
    # the over-quantity guard below see what the last committed writer left.
    locked_line = await db.scalar(
        select(WmsPickLine)
        .where(WmsPickLine.id == line.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_line is None:
        return scan_response(
            direction,
            'not_found',
            message='The line this scan matched is gone',
        )
    line = locked_line

    tallies = await lot_tallies_async(db, line.id)
    unnamed_quantity = line.picked_quantity - sum(
        (tally.quantity for tally in tallies), Decimal('0')
    )
    adopted: StockLotDTO | None = None
    if lot_code and template_id is not None:
        accepted, adopted = await _lot_the_scan_names_async(
            db,
            session.organization_id,
            line,
            doc_line,
            template_id,
            lot_code,
            unnamed_quantity=unnamed_quantity,
        )
        if not accepted:
            return scan_response(
                direction,
                'wrong_lot',
                line_id=line.id,
                product_name=line.product_name,
                quantity=float(line.picked_quantity),
                expected_quantity=float(line.expected_quantity),
                uom_symbol=line.uom_symbol,
                bin_location=line.bin_location,
                lot_name=line.lot_name,
                message=(
                    f'Lot {lot_code.strip()} is not a lot this line can be '
                    f'picked from — the line expects {line.lot_name or "no lot"}'
                ),
            )

    new_qty = line.picked_quantity + quantity
    over_expected = is_surplus(doc_line, new_qty, line.expected_quantity)
    if over_expected:
        if may_exceed_over_receipt is None:
            return scan_response(
                direction,
                'over_quantity',
                line_id=line.id,
                product_name=line.product_name,
                quantity=float(line.picked_quantity),
                expected_quantity=float(line.expected_quantity),
                uom_symbol=line.uom_symbol,
                bin_location=line.bin_location,
                lot_name=line.lot_name,
                message=(
                    f'Cannot {direction.verb} {quantity} more — already '
                    f'{line.picked_quantity}/{line.expected_quantity} '
                    f'{line.uom_symbol or ""}'
                ),
            )
        await assert_line_over_receipt_allowed_async(
            db,
            doc.organization_id if doc else session.organization_id,
            doc_line,
            exclude_doc_id=doc.id if doc else None,
            quantity=new_qty,
            expected=line.expected_quantity,
            may_exceed=may_exceed_over_receipt,
        )

    named_lot_id = adopted.id if adopted is not None else line.lot_id
    lot_name = adopted.name if adopted is not None else line.lot_name
    taken_from_lot = sum(
        (tally.quantity for tally in tallies if tally.lot_id == named_lot_id),
        Decimal('0'),
    )
    if named_lot_id is not None and template_id and doc and doc_line:
        # The line is booked from the batches it was picked from, each for
        # what it gave, so a quantity that this batch cannot give is refused
        # here, whether the scan names it or continues a line already started:
        # the rest comes from the next batch, scanned with its label.
        if not await lot_covers_async(
            db, doc, doc_line, template_id, named_lot_id, taken_from_lot + quantity
        ):
            # its own word, so the screen says the batch is too small rather
            # than that it is the wrong one; the batch named is the one that
            # cannot give it.
            return scan_response(
                direction,
                'lot_too_small',
                line_id=line.id,
                product_name=line.product_name,
                quantity=float(line.picked_quantity),
                expected_quantity=float(line.expected_quantity),
                uom_symbol=line.uom_symbol,
                bin_location=line.bin_location,
                lot_name=lot_name,
                message=(
                    f'Lot {lot_name} cannot give {taken_from_lot + quantity} '
                    f'{line.uom_symbol or ""} — scan the label of the next '
                    f'lot for the rest'
                ),
            )

    planned_lot_name: str | None = None
    if adopted is not None:
        # only now: a refused scan leaves the lot as it found it. Only the
        # first lot contradicts the plan; the next lot of a line picked from
        # several is the line going as it must.
        if line.picked_quantity == 0:
            planned_lot_name = line.lot_name
        line.lot_id = adopted.id
        line.lot_name = adopted.name
        # the date beside the batch is the batch's, not the plan's
        line.expiry_date = min(
            (d for d in (adopted.use_by_date, adopted.expiry_date) if d), default=None
        )
    if named_lot_id is not None and lot_name:
        await tally_lot_async(db, line, named_lot_id, lot_name, quantity)
    line.picked_quantity = new_qty
    # the stored word is 'picked' for both directions; only the wire word
    # differs, and the response below carries that one.
    line.status = 'picked' if new_qty >= line.expected_quantity else 'pending'

    if doc_line:
        doc_line.done_quantity = new_qty
        if over_expected:
            # a surplus records why, the way a short line does: the code
            # travels with the line into the document, where the office
            # reads it — in its own language — and completion keeps it.
            doc_line.discrepancy_code = SURPLUS_CODE
            doc_line.discrepancy_reason = None

    all_lines = (
        await db.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == session.id)
        )
    ).all()
    session_complete = (
        all(ln.status in ('picked', 'short', 'skipped') for ln in all_lines)
        and destination_awaited(session, all_lines) is None
    )

    # once the last line resolves, close the session — an `active`
    # session left behind blocks the document from ever completing.
    await close_session_if_complete_async(
        db, session, short_status=direction.short_status
    )

    await db.flush()

    lot_warning = ''
    if planned_lot_name:
        lot_warning = f' — lot {line.lot_name}, the plan said {planned_lot_name}'

    return scan_response(
        direction,
        direction.done_word,
        line_id=line.id,
        product_name=line.product_name,
        quantity=float(new_qty),
        expected_quantity=float(line.expected_quantity),
        uom_symbol=line.uom_symbol,
        bin_location=line.bin_location,
        lot_name=line.lot_name,
        planned_lot_name=planned_lot_name,
        expiry_date=line.expiry_date,
        session_complete=session_complete,
        message=(
            f'{line.product_name or "Item"} {direction.done_word} — '
            f'{new_qty}/{line.expected_quantity} {line.uom_symbol or ""}'
            f'{lot_warning}'
        ),
    )
