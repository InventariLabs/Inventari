"""Picking's session start, reads and line planning — thin bindings.

The machine lives in ``_wms_session_ops``. What stays here is what
genuinely differs for picking: the document types it accepts, the group,
batch and shelf each line is planned from, and the shelf-order pass over the
lines it just built. The line helpers are public in this module on purpose —
the unit tests pin them, and that is where the motion of a picking line
lives.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import PickOrderLineDTO, PickOrderLocationDTO, StorageDTO
from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from ._stock_executor_helpers import line_source_shelf
from ._wms_direction import PICKING
from ._wms_line_utils import (  # noqa: F401  (re-exported for existing importers)
    _get_active_session_async,
    _line_template_id,
    _resolve_lot_name,
    _resolve_product_name,
    _resolve_uom_symbol,
    mark_worked_on,
    shelf_caption,
)
from ._wms_session_access import _holder_name_async
from ._wms_session_close import journal_session_async, lot_covers_async
from ._wms_session_ops import (
    get_session_async,
    list_sessions_for_document_async,
    load_document_async,
    open_session_async,
    open_session_holding_async,
    start_session_async,
)
from .models import (
    Document,
    DocumentLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
)
from .pick_order_strategies import resolve_pick_order_strategy_async

#: Document types a picking session may be started on.
PICKABLE_TYPES = {'OUT', 'WZ', 'RW', 'INTERNAL_OUT', 'INT', 'MM'}


async def start_pick_session_async(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
    user_id: UUID,
) -> WmsPickSession:
    session = await start_session_async(
        db,
        PICKING,
        document_id,
        org_id,
        user_id,
        is_supported=_supports_picking,
        line_fields=_pick_line_fields_async,
        sort_lines=_assign_optimized_pick_order_async,
    )
    await db.flush()
    await db.refresh(session, ['lines'])
    return session


async def start_pick_session_over_documents_async(
    db: AsyncSession,
    document_ids: list[UUID],
    org_id: UUID,
    user_id: UUID,
) -> WmsPickSession:
    """One session over several confirmed dispatches — or the one already open.

    Each document is asked what a start over it alone asks — this
    organization's, confirmed, a dispatch, approved — and one more thing: no
    *other* session holds it, since a document is picked in one session at a
    time. The first document that fails refuses the whole start and the
    sentence names it, so nobody is left with a session over part of what
    they chose.

    A session the caller opened over exactly this selection comes back
    instead, the way a single-document start hands back the session a closed
    tab left behind: the sheet was closed mid-way, the register offers the
    start again, and pressing it has to walk on from the scans already
    recorded rather than refuse the only route back into them. Every
    document asked for has to sit in that one session — a selection it does
    not cover is a different start and stays refused, as does a session
    somebody else holds.
    """
    ordered = list(dict.fromkeys(document_ids))
    # Locks in one order, whatever order the caller listed: two starts over
    # overlapping selections must not each hold the lock the other waits on.
    for document_id in sorted(ordered):
        await acquire_advisory_lock(db, f'{PICKING.lock_prefix}:{document_id}')

    docs: list[Document] = []
    # A document already held does not refuse here: whether one open session
    # holds the whole selection — the resume the docstring promises — is only
    # known once the last document has been asked. The refusal below still
    # names the first held document, in the order the caller listed them.
    held: list[tuple[Document, WmsPickSession]] = []
    for document_id in ordered:
        doc = await load_document_async(db, org_id, document_id, confirmed_only=False)
        if doc is None:
            raise ServiceRejectionError(
                'wms_pick_document_not_found', document=str(document_id)
            )
        if doc.status != DocumentStatus.CONFIRMED.value:
            raise ServiceRejectionError(
                'wms_pick_document_not_confirmed', number=doc.number
            )
        if not dt.is_dispatch(doc.type):
            raise ServiceRejectionError(
                'wms_pick_document_not_dispatch', number=doc.number
            )
        open_session = await open_session_holding_async(db, org_id, doc.id)
        if open_session is not None:
            held.append((doc, open_session))
        docs.append(doc)

    if len(held) == len(ordered) and len({session.id for _, session in held}) == 1:
        session = held[0][1]
        if session.assigned_to == user_id:
            # The session is in somebody's hands again: its idle clock starts
            # over and a sheet that was closed mid-way counts as running —
            # what the sheet about to reopen needs it to be.
            mark_worked_on(session)
            await db.refresh(session, ['lines'])
            return session

    if held:
        doc, open_session = held[0]
        raise ServiceRejectionError(
            'wms_pick_document_in_session',
            number=doc.number,
            owner=await _holder_name_async(db, org_id, open_session.assigned_to),
        )

    session = await open_session_async(
        db,
        PICKING,
        docs,
        org_id,
        user_id,
        line_fields=_pick_line_fields_async,
        sort_lines=_assign_optimized_pick_order_async,
    )
    await journal_session_async(db, session, user_id, docs)
    # The request owns the commit (``get_async_db`` commits on success).
    await db.refresh(session, ['lines'])
    return session


async def get_pick_session_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
) -> WmsPickSession | None:
    return await get_session_async(db, session_id, org_id)


async def list_pick_sessions_for_document_async(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
) -> list[WmsPickSession]:
    return await list_sessions_for_document_async(
        db, document_id, org_id, inbound_only=False
    )


def _supports_picking(doc_type: str) -> bool:
    return doc_type in PICKABLE_TYPES


async def _pick_line_fields_async(
    db: AsyncSession, line: DocumentLine, doc: Document
) -> dict[str, Any]:
    """What a picking line points at: its group and batch, and its shelf as text.

    The organization comes from the document: the machine fetched it under
    that organization, so a line cannot belong to another one.
    """
    org_id = doc.organization_id
    return {
        **await _assign_pick_group_async(db, org_id, line, doc),
        'bin_location': await _resolve_bin_location_async(db, line, doc, org_id),
        'location_id': _line_location_id(line, doc),
    }


def _line_location_id(line: DocumentLine, doc: Document) -> UUID | None:
    """The shelf the picker is sent to for this line: the line's own pin, else the document's.

    The record is read only when neither names a shelf, the one place the
    line's own stock decides the shelf.
    """
    if line.source_location_id is not None or doc.source_location_id is not None:
        return line_source_shelf(line, doc, None)
    return line_source_shelf(line, doc, line.item)


async def _location_chain_async(
    db: AsyncSession,
    org_id: UUID,
    location_id: UUID,
    cache: dict[UUID, StorageDTO | None],
) -> list[StorageDTO]:
    """The location and its ancestors, the outermost first.

    Guarded against a cycle in the parent links, which older data can hold.
    """
    chain: list[StorageDTO] = []
    seen: set[UUID] = set()
    current: UUID | None = location_id
    while current is not None and current not in seen:
        seen.add(current)
        if current not in cache:
            cache[current] = await core_api.locations.get_async(db, org_id, current)
        loc = cache[current]
        if loc is None:
            break
        chain.append(loc)
        current = loc.parent_id
    chain.reverse()
    return chain


async def _assign_pick_group_async(
    db: AsyncSession, org_id: UUID, line: DocumentLine, doc: Document
) -> dict[str, Any]:
    """The group and lot this line plans from.

    The document's own hold counts as available to it, so a line whose whole
    quantity the confirmation reserved on the strategy's first lot still
    plans that lot rather than the next one.

    Empty dict for a line that names no product or a shelf nothing has
    stocked — the line then keeps the shape it had: no group, no lot, and
    the document decides the match when a scan comes in.
    """
    template_id = _line_template_id(line)
    if not template_id:
        return {}

    group = await core_api.stock.find_best_pick_group_for_picking_async(
        db,
        org_id,
        template_id,
        _line_location_id(line, doc),
        except_document_id=doc.id,
    )
    if group is None:
        return {}
    fields: dict[str, Any] = {
        'anchor_id': group.anchor_id,
        'lot_id': group.lot_id,
        # The date of what the draw reaches first: the batch's, or the
        # record's own where the stock carries no batch.
        'expiry_date': group.expiry_date,
    }
    if group.lot_id is not None:
        if await lot_covers_async(
            db, doc, line, template_id, group.lot_id, line.quantity
        ):
            # The row names the batch it plans, so the picker reads what to
            # look for; a batch the document line names itself is read from
            # there.
            fields['planned_lot_name'] = await _lot_name_async(
                db, org_id, template_id, group.lot_id
            )
        else:
            # No batch gives the whole line: none is planned, so none is
            # picked and booked, and the strategy serves the line across
            # batches.
            fields['lot_id'] = None
            fields['expiry_date'] = None
    return fields


async def _lot_name_async(
    db: AsyncSession, org_id: UUID, template_id: UUID, lot_id: UUID
) -> str | None:
    lots = await core_api.stock.list_lots_async(db, org_id, template_id)
    return next((lot.name for lot in lots if lot.id == lot_id), None)


class WalkedLine(NamedTuple):
    """One line the walk is asked to order, whoever's it is.

    *key* is whatever the caller finds the line by afterwards — a pick line's
    id on a session, a document line's on a dispatch not yet picked.
    """

    key: UUID
    line: DocumentLine
    doc: Document
    product_name: str | None
    quantity: Decimal
    lot_name: str | None
    bin_location: str | None


async def walk_order_async(
    db: AsyncSession, org_id: UUID, lines: list[WalkedLine]
) -> dict[UUID, int]:
    """Each line's place in the walk, by key — the one function both the
    session screen and the paper pick list read, so they cannot disagree.

    The walk itself is a strategy (see ``pick_order_strategies``): the
    default orders by the numbers of the locations — each ancestor's, then
    the location's own, a level without a number after the numbered ones,
    equal paths falling back to the code and then the name, and lines with no
    location at all last — and an organization may have chosen a module's
    own in the warehouse settings.
    """
    if not lines:
        return {}
    strategy = await resolve_pick_order_strategy_async(db, org_id)
    cache: dict[UUID, StorageDTO | None] = {}
    walked: list[PickOrderLineDTO] = []
    for entry in lines:
        location_id = _line_location_id(entry.line, entry.doc)
        chain = (
            await _location_chain_async(db, org_id, location_id, cache)
            if location_id is not None
            else []
        )
        walked.append(
            PickOrderLineDTO(
                id=entry.key,
                product_template_id=_line_template_id(entry.line),
                product_name=entry.product_name,
                quantity=entry.quantity,
                lot_name=entry.lot_name,
                location_id=location_id,
                location_path=[
                    PickOrderLocationDTO(
                        id=loc.id,
                        sequence=loc.sequence,
                        short_code=loc.short_code,
                        name=loc.name,
                    )
                    for loc in chain
                ],
                bin_location=entry.bin_location,
            )
        )
    return {line.id: i for i, line in enumerate(await strategy(db, org_id, walked))}


async def _assign_optimized_pick_order_async(
    db: AsyncSession, session_id: UUID
) -> None:
    """Order the lines the way the organization walks the warehouse.

    Each line is read through its own document, not the session's: a session
    over several dispatches walks all of their lines in one order.
    """
    rows = (
        await db.execute(
            select(WmsPickLine, DocumentLine, Document)
            .join(DocumentLine, DocumentLine.id == WmsPickLine.document_line_id)
            .join(Document, Document.id == DocumentLine.document_id)
            .where(WmsPickLine.session_id == session_id)
            .order_by(WmsPickLine.pick_order)
            .options(selectinload(DocumentLine.item))
        )
    ).all()
    if rows:
        order = await walk_order_async(
            db,
            rows[0][2].organization_id,
            [
                WalkedLine(
                    pick_line.id,
                    line,
                    doc,
                    pick_line.product_name,
                    pick_line.expected_quantity,
                    pick_line.lot_name,
                    pick_line.bin_location,
                )
                for pick_line, line, doc in rows
            ],
        )
        for pick_line, _, _ in rows:
            pick_line.pick_order = order[pick_line.id]
    await db.flush()


async def _resolve_bin_location_async(
    db: AsyncSession, line: DocumentLine, doc: Document, org_id: UUID
) -> str | None:
    """The shelf as the floor reads it: its code, and the name beside it.

    The code alone got a worker to the aisle but named nothing the rest of
    the app says — the picker's row said "SEED-C2S1" while every other screen
    called the same shelf "Shelf B - Bottom". The name is only dropped when
    the shelf never got one, and the code when it has none: the row always
    carries whatever there is to read.
    """
    parts = []
    location_id = _line_location_id(line, doc)
    if location_id:
        loc = await core_api.locations.get_async(db, org_id, location_id)
        if loc:
            parts.append(shelf_caption(loc))
    sku = line.sku
    if sku:
        parts.append(sku)
    return ' / '.join(parts) if parts else None
