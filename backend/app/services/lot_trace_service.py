"""A batch's trace for a recall: one step back, one step forward.

EU 178/2002 Art. 18 asks every food business to name the immediate supplier
and the immediate customer of what it handled, with quantities and dates.
Every fact is in the ledger already — each movement of a batch carries its
date, quantity and source — and the lot page does the adding up rather than
leaving the raw rows to the reader.

The trace reads the ledger by source instead of by row. Every movement of the
batch under one reference nets into one entry, in or out; movements between
two shelves are left out, because the goods never left the house. The module
that wrote a source names it (``app.core.lot_trace``): the document number,
the partner. A source that transforms — a production run that consumed the
batch and made another — is followed to the batch it made, and that batch's
own trace is appended, so a recall of an ingredient reaches the customers of
the product made from it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    LotTraceDTO,
    LotTraceEntryDTO,
    LotTraceLotDTO,
    LotTraceProducedLotDTO,
    LotTraceReferenceDTO,
)
from app.core.lot_trace import get_lot_trace_source
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.uom import Uom
from app.services.pdf_utils import format_partner_address

#: How many batches one trace walks before it stops and says so. A run that
#: fans one ingredient batch out into hundreds of products is a report of its
#: own, not a page.
MAX_TRACED_LOTS = 50

_IN = 'in'
_OUT = 'out'

#: A key for one source of movements: (reference_type, reference_id).
_Ref = tuple[str | None, UUID | None]


def _moved_at() -> Any:
    return func.coalesce(StockMove.completed_at, StockMove.created_at)


def _signed_quantity() -> Any:
    """The quantity, positive in from outside and negative out to outside.

    A movement with both ends on a shelf is filtered out before this is read.
    """
    return case(
        (StockMove.from_location_id.is_(None), StockMove.quantity),
        else_=-StockMove.quantity,
    )


async def _lot_headers_async(
    db: AsyncSession, organization_id: UUID, lot_ids: Iterable[UUID]
) -> dict[UUID, tuple[StockLot, str | None, str | None]]:
    ids = list(lot_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(StockLot, ProductTemplate.name, Uom.symbol)
            .outerjoin(
                ProductTemplate, ProductTemplate.id == StockLot.product_template_id
            )
            .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
            .where(StockLot.id.in_(ids), StockLot.organization_id == organization_id)
        )
    ).all()
    return {lot.id: (lot, product, uom) for lot, product, uom in rows}


async def _net_by_reference_async(
    db: AsyncSession, organization_id: UUID, lot_id: UUID
) -> dict[_Ref, tuple[Decimal, datetime]]:
    """Every source of the batch's crossings, with its net quantity and date.

    Positive is in, negative is out. A source that nets to nothing — a run
    undone, a receipt corrected away under its own reference — is dropped.
    """
    rows = (
        await db.execute(
            select(
                StockMove.reference_type,
                StockMove.reference_id,
                func.sum(_signed_quantity()),
                func.max(_moved_at()),
            )
            .where(
                StockMove.organization_id == organization_id,
                StockMove.lot_id == lot_id,
                # Shelf to shelf is not a crossing.
                StockMove.from_location_id.is_(None)
                | StockMove.to_location_id.is_(None),
            )
            .group_by(StockMove.reference_type, StockMove.reference_id)
        )
    ).all()
    return {
        (reference_type, reference_id): (quantity, at)
        for reference_type, reference_id, quantity, at in rows
        if quantity != 0
    }


async def _produced_lots_async(
    db: AsyncSession,
    organization_id: UUID,
    reference_type: str,
    reference_ids: list[UUID],
    consumed_lot_id: UUID,
) -> dict[UUID, list[LotTraceProducedLotDTO]]:
    """The batches each transforming reference made, netted per batch."""
    rows = (
        await db.execute(
            select(
                StockMove.reference_id,
                StockMove.lot_id,
                StockLot.name,
                ProductTemplate.name,
                Uom.symbol,
                func.sum(_signed_quantity()),
            )
            .join(StockLot, StockLot.id == StockMove.lot_id)
            .outerjoin(
                ProductTemplate, ProductTemplate.id == StockLot.product_template_id
            )
            .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
            .where(
                StockMove.organization_id == organization_id,
                StockMove.reference_type == reference_type,
                StockMove.reference_id.in_(reference_ids),
                StockMove.lot_id != consumed_lot_id,
                StockMove.from_location_id.is_(None)
                | StockMove.to_location_id.is_(None),
            )
            .group_by(
                StockMove.reference_id,
                StockMove.lot_id,
                StockLot.name,
                ProductTemplate.name,
                Uom.symbol,
            )
            .order_by(StockLot.name)
        )
    ).all()
    made: dict[UUID, list[LotTraceProducedLotDTO]] = defaultdict(list)
    for reference_id, lot_id, lot_name, product, uom, quantity in rows:
        # The other ingredients of the same run went *out* under it; only
        # what came in is what the run made.
        if quantity > 0:
            made[reference_id].append(
                LotTraceProducedLotDTO(
                    lot_id=lot_id,
                    lot_name=lot_name,
                    product_name=product,
                    uom_symbol=uom,
                    quantity=quantity,
                )
            )
    return made


async def _describe_async(
    db: AsyncSession, organization_id: UUID, refs: Iterable[_Ref]
) -> dict[_Ref, LotTraceReferenceDTO]:
    by_type: dict[str, list[UUID]] = defaultdict(list)
    for reference_type, reference_id in refs:
        if reference_type is not None and reference_id is not None:
            by_type[reference_type].append(reference_id)
    described: dict[_Ref, LotTraceReferenceDTO] = {}
    for reference_type, ids in by_type.items():
        source = get_lot_trace_source(reference_type)
        if source is None:
            continue
        answers = await source.describe_async(db, organization_id, ids)
        for reference_id, answer in answers.items():
            described[(reference_type, reference_id)] = answer
    return described


async def _partners_async(
    db: AsyncSession, organization_id: UUID, partner_ids: set[UUID]
) -> dict[UUID, tuple[str, dict[str, Any] | None]]:
    if not partner_ids:
        return {}
    rows = (
        await db.execute(
            select(Partner.id, Partner.name, Partner.address).where(
                Partner.id.in_(partner_ids),
                Partner.organization_id == organization_id,
            )
        )
    ).all()
    return {partner_id: (name, address) for partner_id, name, address in rows}


async def _trace_one_lot_async(
    db: AsyncSession,
    organization_id: UUID,
    lot_id: UUID,
    lang: str,
) -> tuple[list[LotTraceEntryDTO], list[LotTraceEntryDTO]]:
    net = await _net_by_reference_async(db, organization_id, lot_id)
    described = await _describe_async(db, organization_id, net)

    produced: dict[_Ref, list[LotTraceProducedLotDTO]] = {}
    transforming: dict[str, list[UUID]] = defaultdict(list)
    for (reference_type, reference_id), (quantity, _) in net.items():
        source = get_lot_trace_source(reference_type)
        if (
            quantity < 0
            and source is not None
            and source.transforms
            and reference_id is not None
        ):
            transforming[source.reference_type].append(reference_id)
    for reference_type, ids in transforming.items():
        made = await _produced_lots_async(
            db, organization_id, reference_type, ids, lot_id
        )
        for reference_id, lots in made.items():
            produced[(reference_type, reference_id)] = lots

    missing = {
        answer.partner_id
        for answer in described.values()
        if answer.partner_id is not None and answer.partner_name is None
    }
    partners = await _partners_async(db, organization_id, missing)

    received: list[LotTraceEntryDTO] = []
    sent: list[LotTraceEntryDTO] = []
    for key, (quantity, moved_at) in net.items():
        reference_type, reference_id = key
        answer = described.get(key) or LotTraceReferenceDTO()
        name, address = answer.partner_name, answer.partner_address
        if name is None and answer.partner_id in partners:
            name, address = partners[answer.partner_id]
        entry = LotTraceEntryDTO(
            direction=_IN if quantity > 0 else _OUT,
            reference_type=reference_type,
            reference_id=reference_id,
            label=answer.label,
            partner_id=answer.partner_id,
            partner_name=name,
            partner_address=format_partner_address(address, lang),
            moved_at=moved_at,
            quantity=abs(quantity),
            produced=produced.get(key, []),
        )
        (received if quantity > 0 else sent).append(entry)
    received.sort(key=lambda entry: entry.moved_at)
    sent.sort(key=lambda entry: entry.moved_at)
    return received, sent


async def trace_lot_async(
    db: AsyncSession,
    organization_id: UUID,
    lot_id: UUID,
    *,
    lang: str = 'en',
) -> LotTraceDTO | None:
    """The batch's suppliers and customers, then those of what was made of it.

    ``None`` when the batch is not this organization's.
    """
    headers = await _lot_headers_async(db, organization_id, [lot_id])
    if lot_id not in headers:
        return None

    queue: list[tuple[UUID, UUID | None]] = [(lot_id, None)]
    seen = {lot_id}
    lots: list[LotTraceLotDTO] = []
    truncated = False
    while queue:
        current, made_from = queue.pop(0)
        if current not in headers:
            headers.update(await _lot_headers_async(db, organization_id, [current]))
        if current not in headers:
            continue
        lot, product_name, uom_symbol = headers[current]
        received, sent = await _trace_one_lot_async(db, organization_id, current, lang)
        lots.append(
            LotTraceLotDTO(
                lot_id=lot.id,
                lot_name=lot.name,
                product_name=product_name,
                uom_symbol=uom_symbol,
                expiry_date=lot.expiry_date,
                made_from_lot_id=made_from,
                received=received,
                sent=sent,
            )
        )
        for entry in sent:
            for made in entry.produced:
                if made.lot_id in seen:
                    continue
                if len(seen) >= MAX_TRACED_LOTS:
                    truncated = True
                    continue
                seen.add(made.lot_id)
                queue.append((made.lot_id, current))
    return LotTraceDTO(lot_id=lot_id, lots=lots, truncated=truncated)


def trace_to_export_frame(trace: LotTraceDTO, tz: Any) -> Any:
    """The trace as one sheet: a row per crossing, in the batch's order.

    One flat table rather than a sheet per batch: an inspector filters and
    sums a column, and every row says which batch and product it is about.
    Dates go out in the reader's clock without an offset, the way the
    ledger's export does (Excel refuses an aware datetime).
    """
    import pandas as pd

    columns = [
        'Batch',
        'Product',
        'Made from batch',
        'Direction',
        'Date',
        'Source',
        'Document',
        'Partner',
        'Partner address',
        'Quantity',
        'Unit',
        'Made into',
    ]
    names = {lot.lot_id: lot.lot_name for lot in trace.lots}
    rows = []
    for lot in trace.lots:
        for entry in [*lot.received, *lot.sent]:
            rows.append(
                {
                    'Batch': lot.lot_name,
                    'Product': lot.product_name,
                    'Made from batch': names.get(lot.made_from_lot_id)
                    if lot.made_from_lot_id
                    else None,
                    'Direction': 'In' if entry.direction == _IN else 'Out',
                    'Date': entry.moved_at.astimezone(tz).replace(tzinfo=None),
                    'Source': entry.reference_type,
                    'Document': entry.label,
                    'Partner': entry.partner_name,
                    'Partner address': entry.partner_address,
                    'Quantity': float(entry.quantity),
                    'Unit': lot.uom_symbol,
                    'Made into': ', '.join(
                        f'{made.lot_name} ({made.product_name})'
                        if made.product_name
                        else made.lot_name
                        for made in entry.produced
                    )
                    or None,
                }
            )
    return pd.DataFrame(rows, columns=columns)
