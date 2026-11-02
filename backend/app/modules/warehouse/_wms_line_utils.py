"""Shared WMS document-line helpers for picking and receiving sessions.

These helpers were previously duplicated between ``_picking_helpers.py``
and ``_receiving_helpers.py`` with identical behavior. They are
consolidated here; both sides re-export them so existing imports keep
working. The refusal they raise speaks one sentence in the reader's
language — the screen already says which direction the session runs.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.barcode import normalize_barcode
from app.core.contracts import StorageDTO
from app.core.exceptions import ServiceRejectionError

from .models import DocumentLine, WmsPickSession, WmsPickSessionDocument


def shelf_caption(shelf: StorageDTO) -> str:
    """A shelf as the floor reads it: its code, and the name beside it.

    The code alone got a worker to the aisle but named nothing the rest of
    the app says; the name is dropped only when the shelf never got one, and
    the code when it has none.
    """
    if shelf.short_code and shelf.name and shelf.short_code != shelf.name:
        return f'{shelf.short_code} · {shelf.name}'
    return shelf.short_code or shelf.name


def _resolve_product_name(line: DocumentLine) -> str | None:
    product_name: str | None = None
    if line.product_template:
        product_name = line.product_template.name
    elif line.item:
        product_name = line.item.name
    else:
        product_name = line.name
    return product_name


def _resolve_lot_name(line: DocumentLine) -> str | None:
    lot_name: str | None = None
    if line.batch_number:
        lot_name = line.batch_number
    elif line.serial_number:
        lot_name = line.serial_number
    return lot_name


def _resolve_uom_symbol(line: DocumentLine) -> str | None:
    """The unit the session row prints, taken from the line or from the stock.

    The line is asked first: it recorded the unit the document was written
    in. A line written before that inheritance existed carries none, and its
    picker would read a bare quantity — so the record the line names answers
    instead, exactly as it does for the product name a few lines above.

    Both fallback sources are eager-loaded (``lazy='selectin'`` on each
    relationship), so reading them here does not fire a lazy load inside
    the async session.
    """
    if line.uom:
        return cast(str, line.uom.symbol)
    if line.item is not None and line.item.uom is not None:
        return cast(str, line.item.uom.symbol)
    if line.product_template is not None and line.product_template.uom is not None:
        return cast(str, line.product_template.uom.symbol)
    return None


async def _get_active_session_async(
    db: AsyncSession, session_id: UUID, org_id: UUID
) -> WmsPickSession:
    """Return the active/paused session, or refuse with a keyed sentence.

    Every operation on a session goes through here, so this is where the
    session is marked worked on: a paused one is held again, and its idle
    time starts over.
    """
    session = await db.scalar(
        select(WmsPickSession).where(
            WmsPickSession.id == session_id,
            WmsPickSession.organization_id == org_id,
            WmsPickSession.status.in_(['active', 'paused']),
        )
    )
    if not session:
        raise ServiceRejectionError('wms_session_not_found')
    mark_worked_on(session)
    return session


def mark_worked_on(session: WmsPickSession) -> None:
    """The session is in someone's hands again, as of now."""
    session.status = 'active'
    session.last_activity_at = datetime.now(UTC)


def session_holds_document(document_id: UUID) -> ColumnElement[bool]:
    """Whether a session row picks *document_id*.

    A session's first document is its ``document_id``; a session over
    several dispatches lists the others in ``WmsPickSessionDocument``. Every
    question asked "by document" — which sessions does it have, is one still
    open on it — reads both, or a dispatch picked second would look free.
    """
    return or_(
        WmsPickSession.document_id == document_id,
        WmsPickSession.id.in_(
            select(WmsPickSessionDocument.session_id).where(
                WmsPickSessionDocument.document_id == document_id
            )
        ),
    )


async def session_document_ids_async(
    db: AsyncSession, session: WmsPickSession
) -> list[UUID]:
    """The session's documents in the order it was asked for.

    A session with no list is the session of its ``document_id`` alone.
    """
    listed = (
        await db.scalars(
            select(WmsPickSessionDocument.document_id)
            .where(WmsPickSessionDocument.session_id == session.id)
            .order_by(WmsPickSessionDocument.position)
        )
    ).all()
    return list(listed) or [session.document_id]


async def document_lines_by_id_async(
    db: AsyncSession, ids: Iterable[UUID]
) -> dict[UUID, DocumentLine]:
    """The document lines behind a session's lines, in one query.

    A loop over the session's lines that read its document line each turn
    cost one ``SELECT`` per line; the whole set is fetched once and looked up
    in memory.
    """
    wanted = list(ids)
    if not wanted:
        return {}
    rows = await db.scalars(select(DocumentLine).where(DocumentLine.id.in_(wanted)))
    return {row.id: row for row in rows.all()}


def _line_template_id(line: DocumentLine) -> UUID | None:
    """The template a line picks from — its own, or the one behind its item.

    A line built by the scanner carries ``item_id`` alone, a line built by the
    product search carries ``product_template_id`` alone, and both name the same
    shelf. Resolving either is what keeps a picking session from silently
    dropping half the lines a receiving session would have shown.
    """
    if line.product_template_id:
        return cast('UUID | None', line.product_template_id)
    item = line.item
    return cast('UUID | None', item.template_id) if item is not None else None


def _line_matches_scan(
    line: DocumentLine | None, template_id: UUID, scanned_barcode: str
) -> bool:
    """Whether a scan of *template_id* is a scan of this document line.

    The product the line names decides, through its own template or through
    its record. A line that names neither -- typed by hand -- can only answer
    with the barcode written on it, compared in the form the catalogue lookup
    produced for the scan: a UPC-A on the line is the same product as the
    EAN-13 the lookup resolved, and a raw string comparison called them two.
    """
    if line is None:
        return False
    line_template = _line_template_id(line)
    if line_template is not None:
        return line_template == template_id
    stored = normalize_barcode(line.barcode)
    return stored is not None and stored == normalize_barcode(scanned_barcode)
