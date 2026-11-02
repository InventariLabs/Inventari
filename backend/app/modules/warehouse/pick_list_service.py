"""The paper pick list — a dispatch or a pick session, lines in walk order.

A small business without scanners starts on paper, and paper has to say the
same thing the screen says. The order is therefore not computed a second
time here: a session's list reads the order its lines were given when the
session was opened, and a dispatch not yet picked is walked through
``walk_order_async`` — the function the session itself is ordered by.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StorageDTO
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from ._picking_helpers import (
    WalkedLine,
    _pick_line_fields_async,
    walk_order_async,
)
from ._print_template_pick import pick_pick_list_html
from ._wms_line_utils import (
    _resolve_lot_name,
    _resolve_product_name,
    _resolve_uom_symbol,
    session_document_ids_async,
)
from ._wms_session_ops import load_document_async
from .document_pdf_service import generate_pick_list_pdf_async
from .models import Document, DocumentLine, DocumentStatus, WmsPickLine, WmsPickSession


def _row(
    shelf: StorageDTO | None,
    line: DocumentLine,
    doc: Document,
    *,
    quantity: Any,
    unit: str | None,
    name: str | None,
    lot: str | None,
) -> dict[str, Any]:
    return {
        'shelf_code': (shelf.short_code or shelf.name) if shelf else None,
        'shelf_name': shelf.name if shelf and shelf.short_code else None,
        'quantity': quantity,
        'unit': unit,
        'name': name,
        'sku': line.sku,
        'lot': lot,
        'document_number': doc.number,
    }


async def _shelf_async(
    db: AsyncSession,
    org_id: UUID,
    location_id: UUID | None,
    cache: dict[UUID, StorageDTO | None],
) -> StorageDTO | None:
    if location_id is None:
        return None
    if location_id not in cache:
        cache[location_id] = await core_api.locations.get_async(db, org_id, location_id)
    return cache[location_id]


async def _dispatch_rows_async(
    db: AsyncSession, org_id: UUID, doc: Document
) -> list[dict[str, Any]]:
    """The lines of a dispatch nobody has started picking, in walk order.

    Each line is planned exactly as opening a session would plan it (its
    shelf, its batch), then put through the same walk.
    """
    planned: list[tuple[WalkedLine, UUID | None]] = []
    for line in doc.lines:
        fields = await _pick_line_fields_async(db, line, doc)
        planned.append(
            (
                WalkedLine(
                    line.id,
                    line,
                    doc,
                    _resolve_product_name(line),
                    line.expected_quantity,
                    _resolve_lot_name(line) or fields.get('planned_lot_name'),
                    fields['bin_location'],
                ),
                fields['location_id'],
            )
        )
    order = await walk_order_async(db, org_id, [walked for walked, _ in planned])
    cache: dict[UUID, StorageDTO | None] = {}
    return [
        _row(
            await _shelf_async(db, org_id, location_id, cache),
            walked.line,
            doc,
            quantity=walked.quantity,
            unit=_resolve_uom_symbol(walked.line),
            name=walked.product_name,
            lot=walked.lot_name,
        )
        for walked, location_id in sorted(planned, key=lambda p: order[p[0].key])
    ]


async def _session_rows_async(
    db: AsyncSession, org_id: UUID, session: WmsPickSession
) -> list[dict[str, Any]]:
    """The session's lines in the order its screen shows them."""
    result = await db.execute(
        select(WmsPickLine, DocumentLine, Document)
        .join(DocumentLine, DocumentLine.id == WmsPickLine.document_line_id)
        .join(Document, Document.id == DocumentLine.document_id)
        .where(WmsPickLine.session_id == session.id)
        .order_by(WmsPickLine.pick_order)
    )
    cache: dict[UUID, StorageDTO | None] = {}
    return [
        _row(
            await _shelf_async(db, org_id, pick_line.location_id, cache),
            line,
            doc,
            quantity=pick_line.expected_quantity,
            unit=pick_line.uom_symbol,
            name=pick_line.product_name,
            lot=pick_line.lot_name,
        )
        for pick_line, line, doc in result.all()
    ]


async def _pdf_async(
    db: AsyncSession,
    org_id: UUID,
    documents: list[Document],
    rows: list[dict[str, Any]],
    lang: str,
) -> bytes:
    return await generate_pick_list_pdf_async(
        documents,
        rows,
        template_html=await pick_pick_list_html(db, org_id),
        lang=lang,
        organization=await core_api.organizations.get_async(db, org_id),
    )


async def dispatch_pick_list_async(
    db: AsyncSession, org_id: UUID, document_id: UUID, lang: str
) -> tuple[str, bytes]:
    """``(file name, PDF)`` of a confirmed dispatch's pick list.

    Printable while the dispatch waits to be picked — the same state a pick
    session may start from.
    """
    doc = await load_document_async(db, org_id, document_id, confirmed_only=False)
    if doc is None:
        raise EntityNotFoundError('document')
    if doc.status != DocumentStatus.CONFIRMED.value:
        raise ServiceRejectionError(
            'wms_pick_document_not_confirmed', number=doc.number
        )
    if not dt.is_dispatch(doc.type):
        raise ServiceRejectionError('wms_pick_document_not_dispatch', number=doc.number)
    rows = await _dispatch_rows_async(db, org_id, doc)
    return doc.number, await _pdf_async(db, org_id, [doc], rows, lang)


async def session_pick_list_async(
    db: AsyncSession, org_id: UUID, session: WmsPickSession, lang: str
) -> tuple[str, bytes]:
    """``(file name, PDF)`` of a pick session's list, over all its documents."""
    documents = [
        doc
        for doc_id in await session_document_ids_async(db, session)
        if (doc := await load_document_async(db, org_id, doc_id, confirmed_only=False))
    ]
    rows = await _session_rows_async(db, org_id, session)
    return documents[0].number, await _pdf_async(db, org_id, documents, rows, lang)
