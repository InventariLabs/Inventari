"""Which dispatches stock cannot cover, asked before a pick walk starts.

A picking session starts over a confirmed dispatch whatever the shelves hold
now. Confirmation reserved the stock, but a count, a scrap or a move since
then can leave the document short, and the picker used to learn it at the
shelf, one line at a time. This reads the same records the walk will draw
from and names every line that will come back short, so the person can start
without those documents or with them anyway.

What counts as available to a document: the free stock of its product on the
shelf its lines pick from, the document's own reservation included (it holds
that stock for itself) and every other document's left out. Stock a picker
cannot take does not count: a batch under quarantine, the shelf the receiving
profile names as quarantine, and any warehouse's receiving area, where goods
wait for putaway.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from . import document_types as dt
from ._receiving_area import list_receiving_modes_async
from ._stock_executor_helpers import _resolve_lot, line_source_shelf
from ._wms_line_utils import (
    _line_template_id,
    _resolve_product_name,
    _resolve_uom_symbol,
)
from ._wms_session_ops import load_document_async, open_session_holding_async
from .document_profile_service import get_profile
from .models import Document, DocumentLine, DocumentStatus


@dataclass(frozen=True)
class UncoveredLine:
    """One product of a dispatch that the stock on its shelf cannot cover."""

    product_name: str | None
    uom_symbol: str | None
    ordered: Decimal
    available: Decimal


@dataclass(frozen=True)
class UncoveredDocument:
    document_id: UUID
    document_number: str
    lines: list[UncoveredLine]


async def _unpickable_shelves_async(db: AsyncSession, org_id: UUID) -> set[UUID]:
    """Shelves whose stock a picker may not take: quarantine and receiving areas.

    An area's shelves count with it, and an area stays one after its
    warehouse went back to receiving in one step — goods waiting there are
    still waiting.
    """
    roots: set[UUID] = set()
    profile = await get_profile(db, org_id)
    if profile is not None and profile.quarantine_location_id is not None:
        roots.add(profile.quarantine_location_id)
    for mode in await list_receiving_modes_async(db, org_id):
        if mode.receiving_location_id is not None:
            roots.add(mode.receiving_location_id)
    shelves = set(roots)
    for root in roots:
        shelves.update(await core_api.locations.descendant_ids_async(db, org_id, root))
    return shelves


async def _free_for_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    template_id: UUID,
    skip_shelves: set[UUID],
) -> Decimal:
    """What the line's shelf has free for this document, in the stock unit."""
    shelf = line_source_shelf(line, doc, line.item)
    among = None
    if shelf is not None:
        among = [
            shelf,
            *await core_api.locations.descendant_ids_async(
                db, doc.organization_id, shelf
            ),
        ]
    draws = await core_api.stock.plan_draw_async(
        db,
        doc.organization_id,
        template_id,
        None,
        None,
        lot_id=await _resolve_lot(db, doc, line, create_if_missing=False),
        except_document_id=doc.id,
        among_shelves=among,
    )
    return sum(
        (d.consumed for d in draws if d.location_id not in skip_shelves),
        Decimal('0'),
    )


async def uncovered_documents_async(
    db: AsyncSession, org_id: UUID, document_ids: list[UUID]
) -> list[UncoveredDocument]:
    """The dispatches among *document_ids* whose lines stock cannot cover.

    A document that is not a confirmed dispatch of this organization is not
    this question's to refuse — the start that follows says so — and is left
    out. So is one an open session already holds: the start hands that
    session back whole, so leaving the document out is a choice it could not
    keep, and what was short was named when the session began. Lines of one
    product on one shelf are weighed together, so two lines cannot each be
    covered by the same units.
    """
    skip_shelves = await _unpickable_shelves_async(db, org_id)
    found: list[UncoveredDocument] = []
    for document_id in dict.fromkeys(document_ids):
        doc = await load_document_async(db, org_id, document_id, confirmed_only=True)
        if doc is None or doc.status != DocumentStatus.CONFIRMED.value:
            continue
        if not dt.is_dispatch(doc.type):
            continue
        if await open_session_holding_async(db, org_id, doc.id) is not None:
            continue
        groups: dict[tuple[UUID, UUID | None, UUID | None], list[DocumentLine]] = {}
        for line in doc.lines:
            template_id = _line_template_id(line)
            if template_id is None or line.expected_quantity <= 0:
                continue
            lot_id = await _resolve_lot(db, doc, line, create_if_missing=False)
            shelf = line_source_shelf(line, doc, line.item)
            groups.setdefault((template_id, shelf, lot_id), []).append(line)
        short: list[UncoveredLine] = []
        for (template_id, _, _), lines in groups.items():
            ordered = sum((ln.expected_quantity for ln in lines), Decimal('0'))
            available = await _free_for_async(
                db, doc, lines[0], template_id, skip_shelves
            )
            if available < ordered:
                short.append(
                    UncoveredLine(
                        product_name=_resolve_product_name(lines[0]),
                        uom_symbol=_resolve_uom_symbol(lines[0]),
                        ordered=ordered,
                        available=available,
                    )
                )
        if short:
            found.append(UncoveredDocument(doc.id, doc.number, short))
    return found
