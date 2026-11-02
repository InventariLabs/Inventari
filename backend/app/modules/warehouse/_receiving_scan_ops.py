"""Receiving's scan matching — one door, then the shared rule.

A receiving scan arrives by barcode only, and matching a barcode to a line
is what receiving does differently: a line built from the UI carries no
template, so its own stored barcode answers, and a product already received
gets the ``already_received`` answer instead of a silent miss. Everything
after a match is ``_wms_scan_ops.execute_scan_async``, shared by both.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._receipt_planning import attach_receipt_plans
from ._receiving_helpers import _get_active_session_async
from ._receiving_session_ops import confirm_short_receive_async
from ._wms_direction import RECEIVING
from ._wms_line_utils import _line_matches_scan
from ._wms_scan_ops import execute_scan_async, scan_response
from ._wms_shelf import (
    answer_shelf_scan_async,
    refuse_unconfirmed_shelf_async,
    shelf_scan_required,
)
from .document_query_service import get_document
from .models import DocumentLine, WmsPickLine


async def _planned_shelves_async(
    db: AsyncSession, org_id: UUID, document_id: UUID
) -> dict[UUID, UUID | None]:
    """Where each document line is to be put away, by the plan the floor screen shows."""
    doc = await get_document(db, org_id, document_id)
    if doc is None:
        return {}
    await attach_receipt_plans(db, doc)
    return {line.id: getattr(line, 'planned_location_id', None) for line in doc.lines}


async def refuse_short_receive_unconfirmed_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    quantity: Decimal,
) -> dict[str, Any] | None:
    """The scan's shelf refusal for a quantity keyed in by hand.

    The short-receive route — which "Receive full amount" calls — books a
    quantity without a scan, so it answers to the same rule: goods received
    (quantity above zero) need the putaway shelf confirmed; zero stays free.
    """
    if quantity <= 0:
        return None
    session = await _get_active_session_async(db, session_id, org_id)
    if not shelf_scan_required(session):
        return None
    line = await db.scalar(
        select(WmsPickLine).where(
            WmsPickLine.id == line_id, WmsPickLine.session_id == session_id
        )
    )
    if line is None:
        return None
    planned = await _planned_shelves_async(db, org_id, session.document_id)
    return await refuse_unconfirmed_shelf_async(
        db, RECEIVING, session, org_id, line, planned.get(line.document_line_id)
    )


def _needs_lot_expiry(
    doc_line: DocumentLine | None, template: object | None, expiry_date: date | None
) -> bool:
    """Whether a quantity booked against this line must first be dated.

    One question for every door that books a received quantity: a FEFO
    product reaches the shelf undated and sorts last unless the expiry is
    on the document line or arrives with the call. The lot may stay empty.
    """
    return (
        doc_line is not None
        and expiry_date is None
        and doc_line.expiry_date is None
        and core_api.stock.resolve_removal_strategy(template) == 'FEFO'
    )


def _needs_lot_expiry_answer(line: WmsPickLine) -> dict[str, Any]:
    """The answer that records nothing and asks for the lot and expiry."""
    return scan_response(
        RECEIVING,
        'needs_lot_expiry',
        line_id=line.id,
        product_name=line.product_name,
        quantity=float(line.picked_quantity),
        expected_quantity=float(line.expected_quantity),
        uom_symbol=line.uom_symbol,
        message='Lot and expiry are needed for this product',
    )


def _keep_lot_expiry(
    doc_line: DocumentLine | None,
    line: WmsPickLine,
    batch_number: str | None,
    expiry_date: date | None,
) -> None:
    """Put the lot and expiry that rode along with an accepted booking on the line."""
    if doc_line is None:
        return
    if expiry_date is not None and doc_line.expiry_date is None:
        doc_line.expiry_date = expiry_date
    if batch_number and doc_line.batch_number is None:
        doc_line.batch_number = batch_number
        line.lot_name = batch_number


async def _refuse_short_receive_undated_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    quantity: Decimal,
    expiry_date: date | None = None,
) -> dict[str, Any] | None:
    """The scan's lot-and-expiry question for a quantity booked by tap.

    "Receive full amount" and the short-receive sheet book a quantity
    without a scan, so a FEFO product would arrive undated through them as
    well. Zero stays free: nothing arrived, so there is nothing to date.
    """
    if quantity <= 0:
        return None
    line = await db.scalar(
        select(WmsPickLine).where(
            WmsPickLine.id == line_id, WmsPickLine.session_id == session_id
        )
    )
    if line is None:
        return None
    doc_line = await db.get(DocumentLine, line.document_line_id)
    if doc_line is None or doc_line.product_template_id is None:
        return None
    template = await core_api.product_templates.get_async(
        db, org_id, doc_line.product_template_id
    )
    if not _needs_lot_expiry(doc_line, template, expiry_date):
        return None
    return _needs_lot_expiry_answer(line)


async def short_receive_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    quantity: Decimal,
    *,
    batch_number: str | None = None,
    expiry_date: date | None = None,
    **confirm: Any,
) -> WmsPickLine | dict[str, Any]:
    """The one door "Receive full amount" and the short-receive sheet share.

    Returns the booked line, or, as a dict, the scan-style answer that asks
    first and records nothing: the shelf to confirm, or the lot and expiry
    of a FEFO product. Both questions sit here, not in the route, so a door
    added later that books a quantity through this function cannot skip
    them. *confirm* is passed on to ``confirm_short_receive_async``.
    """
    refusal = await refuse_short_receive_unconfirmed_async(
        db, session_id, org_id, line_id, quantity
    ) or await _refuse_short_receive_undated_async(
        db, session_id, org_id, line_id, quantity, expiry_date
    )
    if refusal is not None:
        return refusal
    line = await confirm_short_receive_async(
        db, session_id, org_id, line_id, quantity, **confirm
    )
    # Only an accepted booking keeps the lot and expiry that rode along.
    _keep_lot_expiry(
        await db.get(DocumentLine, line.document_line_id),
        line,
        batch_number,
        expiry_date,
    )
    await db.flush()
    return line


async def scan_receive_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    barcode: str | None = None,
    quantity: Decimal = Decimal('1'),
    *,
    batch_number: str | None = None,
    expiry_date: date | None = None,
    may_exceed_over_receipt: bool = False,
    identify: bool = False,
) -> dict[str, Any]:
    session = await _get_active_session_async(db, session_id, org_id)

    all_session_lines = (
        await db.scalars(
            select(WmsPickLine)
            .where(WmsPickLine.session_id == session_id)
            .order_by(WmsPickLine.pick_order)
        )
    ).all()
    pending_lines = [ln for ln in all_session_lines if ln.status == 'pending']
    if not pending_lines:
        return scan_response(
            RECEIVING, 'all_received', message='All lines have been received'
        )

    if not barcode:
        raise ServiceRejectionError('wms_barcode_required')

    planned_shelves: dict[UUID, UUID | None] = {}
    if shelf_scan_required(session):
        planned_shelves = await _planned_shelves_async(db, org_id, session.document_id)
        shelf_answer = await answer_shelf_scan_async(
            db,
            RECEIVING,
            session,
            org_id,
            barcode,
            [planned_shelves.get(ln.document_line_id) for ln in pending_lines],
        )
        if shelf_answer is not None:
            return shelf_answer

    template = await core_api.product_templates.lookup_by_barcode_async(
        db, org_id, barcode
    )

    if not template:
        return scan_response(RECEIVING, 'not_found', message='Product not recognized')

    def _line_matches(doc_line: DocumentLine | None) -> bool:
        return _line_matches_scan(doc_line, template.id, barcode)

    # One query for every DocumentLine the loops below can consult — a
    # per-line SELECT made a missed scan cost one query per session line,
    # twice (once over pending, once over already-received).
    line_ids = [ln.document_line_id for ln in all_session_lines]
    doc_lines = {
        row.id: row
        for row in (
            await db.scalars(select(DocumentLine).where(DocumentLine.id.in_(line_ids)))
        ).all()
    }

    matched_line = next(
        (
            ln
            for ln in pending_lines
            if _line_matches(doc_lines.get(ln.document_line_id))
        ),
        None,
    )

    if not matched_line:
        already_received = [
            ln
            for ln in all_session_lines
            if ln.status in ('picked', 'short', 'skipped')
        ]
        for recv_line in already_received:
            if _line_matches(doc_lines.get(recv_line.document_line_id)):
                return scan_response(
                    RECEIVING,
                    'already_received',
                    line_id=recv_line.id,
                    product_name=recv_line.product_name,
                    quantity=float(recv_line.picked_quantity),
                    expected_quantity=float(recv_line.expected_quantity),
                    uom_symbol=recv_line.uom_symbol,
                    message=(
                        f'{recv_line.product_name or "Item"} already received — '
                        f'{recv_line.picked_quantity}/'
                        f'{recv_line.expected_quantity} '
                        f'{recv_line.uom_symbol or ""}'
                    ),
                )
        return scan_response(
            RECEIVING,
            'not_in_document',
            product_name=template.name,
            message='This product is not in the document',
        )

    if identify:
        # The phone's card counts; this scan only brings the card up. The
        # shelf and the lot are asked when the count is confirmed, through
        # the short-receive door, which asks both the way a scan does.
        return scan_response(
            RECEIVING,
            'identified',
            line_id=matched_line.id,
            product_name=matched_line.product_name,
            quantity=float(matched_line.picked_quantity),
            expected_quantity=float(matched_line.expected_quantity),
            uom_symbol=matched_line.uom_symbol,
        )

    refusal = await refuse_unconfirmed_shelf_async(
        db,
        RECEIVING,
        session,
        org_id,
        matched_line,
        planned_shelves.get(matched_line.document_line_id),
    )
    if refusal is not None:
        return refusal

    doc_line = doc_lines.get(matched_line.document_line_id)
    if _needs_lot_expiry(doc_line, template, expiry_date):
        # A scan carries a code and a quantity, so a FEFO product would reach
        # the shelf undated and sort last. Nothing is recorded: the same scan
        # is sent again with the lot and expiry the worker read off the pack.
        return _needs_lot_expiry_answer(matched_line)

    result = await execute_scan_async(
        db,
        RECEIVING,
        session,
        matched_line,
        quantity,
        may_exceed_over_receipt=may_exceed_over_receipt,
    )
    if doc_line is not None and result['status'] == RECEIVING.done_word:
        # Only an accepted scan keeps them: they land on the document line the
        # delivery is received from, and name the batch on the session line.
        _keep_lot_expiry(doc_line, matched_line, batch_number, expiry_date)
        await db.flush()
    return result
