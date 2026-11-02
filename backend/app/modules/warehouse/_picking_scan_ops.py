"""Picking's scan matching — the two doors, then the shared rule.

A picking scan arrives by barcode, and finding the line is what picking
does differently from receiving. Everything after a match — the
CONFIRMED gate, the over-quantity refusal, writing the quantity, closing
the session — is ``_wms_scan_ops.execute_scan_async``, shared by both.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError

from ._picking_helpers import _get_active_session_async
from ._wms_direction import PICKING
from ._wms_line_utils import _line_matches_scan, document_lines_by_id_async
from ._wms_scan_ops import execute_scan_async, scan_response
from ._wms_session_close import destination_awaited
from ._wms_shelf import (
    answer_destination_scan_async,
    answer_shelf_scan_async,
    refuse_unconfirmed_shelf_async,
)
from .models import WmsPickLine, WmsPickSession


async def scan_pick_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    barcode: str | None = None,
    quantity: Decimal = Decimal('1'),
    lot_name: str | None = None,
) -> dict[str, Any]:
    """Pick *quantity* off the line the scan matches.

    A scan reports one physical handling, so it moves the quantity the
    picker declared -- not the whole line. Receiving has always worked
    that way; picking closed the line on the first scan, which turned one
    unit in the hand into four on the document.
    """
    session = await _get_active_session_async(db, session_id, org_id)

    pending_lines = (
        await db.scalars(
            select(WmsPickLine)
            .where(
                WmsPickLine.session_id == session_id,
                WmsPickLine.status == 'pending',
            )
            .order_by(WmsPickLine.pick_order)
        )
    ).all()
    if not pending_lines:
        destination = destination_awaited(
            session,
            (
                await db.scalars(
                    select(WmsPickLine).where(WmsPickLine.session_id == session_id)
                )
            ).all(),
        )
        if destination is not None and barcode:
            return await answer_destination_scan_async(
                db, PICKING, session, org_id, barcode, destination
            )
        return scan_response(
            PICKING, 'all_picked', message='All lines have been picked'
        )

    if not barcode:
        raise ServiceRejectionError('wms_barcode_required')
    shelf_answer = await answer_shelf_scan_async(
        db,
        PICKING,
        session,
        org_id,
        barcode,
        [ln.location_id for ln in pending_lines],
    )
    if shelf_answer is not None:
        return shelf_answer
    return await _pick_by_barcode_async(
        db, session, list(pending_lines), barcode, org_id, quantity, lot_name
    )


async def refuse_short_pick_unconfirmed_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    quantity: Decimal,
) -> dict[str, Any] | None:
    """The scan's shelf refusal for a quantity keyed in by hand.

    The short-pick button records a quantity without a scan, so it answers to
    the same rule: goods taken (quantity above zero) need the shelf confirmed;
    "nothing came of this line" stays free.
    """
    if quantity <= 0:
        return None
    session = await _get_active_session_async(db, session_id, org_id)
    line = await db.scalar(
        select(WmsPickLine).where(
            WmsPickLine.id == line_id, WmsPickLine.session_id == session_id
        )
    )
    if line is None:
        return None
    return await refuse_unconfirmed_shelf_async(
        db, PICKING, session, org_id, line, line.location_id
    )


async def _pick_by_barcode_async(
    db: AsyncSession,
    session: WmsPickSession,
    pending_lines: list[WmsPickLine],
    barcode: str,
    org_id: UUID,
    quantity: Decimal,
    lot_name: str | None,
) -> dict[str, Any]:
    from app.core.public_api import core_api

    template = await core_api.product_templates.lookup_by_barcode_async(
        db, org_id, barcode
    )

    if not template:
        return scan_response(PICKING, 'not_found', message='Product not recognized')

    doc_lines = await document_lines_by_id_async(
        db, [ln.document_line_id for ln in pending_lines]
    )
    matched_line = next(
        (
            ln
            for ln in pending_lines
            if _line_matches_scan(
                doc_lines.get(ln.document_line_id), template.id, barcode
            )
        ),
        None,
    )

    if not matched_line:
        done_lines = (
            await db.scalars(
                select(WmsPickLine).where(
                    WmsPickLine.session_id == session.id,
                    WmsPickLine.status.in_(('picked', 'short', 'skipped')),
                )
            )
        ).all()
        done_doc_lines = await document_lines_by_id_async(
            db, [ln.document_line_id for ln in done_lines]
        )
        skipped = None
        for done in done_lines:
            if not _line_matches_scan(
                done_doc_lines.get(done.document_line_id), template.id, barcode
            ):
                continue
            if done.status == 'skipped':
                skipped = skipped or done
                continue
            return scan_response(
                PICKING,
                'already_picked',
                line_id=done.id,
                product_name=done.product_name,
                quantity=float(done.picked_quantity),
                expected_quantity=float(done.expected_quantity),
                uom_symbol=done.uom_symbol,
                message=(
                    f'{done.product_name or "Item"} already picked — '
                    f'{done.picked_quantity}/{done.expected_quantity} '
                    f'{done.uom_symbol or ""}'
                ),
            )
        if skipped is not None:
            # Nothing was picked of it, so "already picked: 0 of N" would be
            # false; the line was put off, and Undo skip brings it back.
            return scan_response(
                PICKING,
                'line_skipped',
                line_id=skipped.id,
                product_name=skipped.product_name,
                expected_quantity=float(skipped.expected_quantity),
                uom_symbol=skipped.uom_symbol,
                message=f'{skipped.product_name or "Item"} was skipped',
            )
        return scan_response(
            PICKING,
            'not_in_document',
            product_name=template.name,
            message='This product is not in the document',
        )

    refusal = await refuse_unconfirmed_shelf_async(
        db, PICKING, session, org_id, matched_line, matched_line.location_id
    )
    if refusal is not None:
        return refusal

    return await execute_scan_async(
        db,
        PICKING,
        session,
        matched_line,
        quantity,
        template_id=template.id,
        lot_code=lot_name,
    )
