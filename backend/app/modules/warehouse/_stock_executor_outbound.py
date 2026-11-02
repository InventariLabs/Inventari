"""Stock executor — outbound operations (dispatch + scrap).

Extracted from document_stock_executor.py to keep the dispatcher under
the 400-LOC module guideline. Both handlers honour lot identity when an
explicit lot is resolved; otherwise the draw is planned from the records
in the removal strategy's order (``take_from_the_records_async``), each
named record written once under the anchors.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemAction, QuantConsumptionDTO
from app.core.exceptions import ServiceRejectionError
from app.core.money import quantise
from app.core.public_api import core_api

from ._stock_executor_helpers import (
    _adopt_card_async,
    _apply_qty_change,
    _base_history,
    _executed_quantity,
    _get_item_or_raise,
    _locked_quantity,
    _post_opening_balance_async,
    _release_the_quarantine_hold_async,
    _require_stock_at,
    _resolve_lot,
    line_source_shelf,
)
from .document_line_split import date_line_by_goods_taken_async
from .models import Document, DocumentLine


async def _take_the_line_off_the_records(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    *,
    item: Any,
    stock_template_id: UUID | None,
    location_id: UUID | None,
    executed_quantity: Decimal,
    lot_id: UUID | None,
    user_id: UUID,
    require_active_lot: bool = True,
) -> list[QuantConsumptionDTO]:
    """Take the line's quantity off the shelf, records first.

    With a ledger behind it (card and shelf named), the draw is planned from
    the records under the anchors and each record the plan names is written
    once, the movements written by the same call, one per batch taken.
    Without one, the record is the whole truth and the line comes off it
    alone. Answers what the records gave up, grain by grain; none for a line
    that came off the record alone.
    """
    if stock_template_id is None or location_id is None:
        if item is not None:
            # No ledger here — nothing mirrors the record, so nothing guesses
            # at it either: the line's quantity comes off the record itself,
            # under its own row lock.
            old_qty = await _locked_quantity(db, doc, item.id)
            await _apply_qty_change(
                db,
                doc,
                item.id,
                old_qty - executed_quantity,
                user_id,
                _base_history(doc),
            )
        return []

    # A scrap takes the goods out by design; an ordinary dispatch of held
    # goods does not and meets the receipt's hold below.
    await _release_the_quarantine_hold_async(
        db,
        doc,
        template_id=stock_template_id,
        shelf_id=location_id,
        quantity=executed_quantity,
        lot_id=lot_id,
    )
    return await core_api.stock.take_from_the_records_async(
        db,
        doc.organization_id,
        stock_template_id,
        location_id,
        executed_quantity,
        lot_id=lot_id,
        user_id=user_id,
        source_document_id=doc.id,
        history_changes=_base_history(doc),
        require_active_lot=require_active_lot,
        # The owner scope follows the one rule every door answers by (the
        # owner comes from the document line — docs/subsystems/STOCK.md):
        # a line that names no owner does not restrict, which is exactly
        # the scope the reservation promised at confirmation. When lines
        # grow an owner column, the door passes it here as owner_id and
        # drops any_owner — the promise and the issue keep answering by
        # the same line either way.
        any_owner=True,
        # The literal, not StockMoveReferenceType: a module does not import
        # a core model. The value is StockMoveReferenceType.DOCUMENT's.
        reference_type='document',
        reference_id=doc.id,
    )


async def dispatch_item(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    user_id: UUID,
    *,
    unit_confirmed_over_template: bool = False,
) -> None:
    """WZ dispatch: decrement item qty, deliver stock, emit StockMove(s)."""
    if not line.item_id:
        raise ServiceRejectionError('document_delivery_lines_reference_items')
    item = await _get_item_or_raise(db, doc.organization_id, line.item_id)
    executed_quantity = _executed_quantity(line)

    stock_template_id = line.product_template_id or item.template_id
    # A record that predates its card holds its stock outside the ledger —
    # and this door's ledger writes were gated on the very id such a row
    # does not have, so the goods left the record while the register read
    # empty. The card comes first, the same adoption the receipt runs, and
    # the block below treats the row as the carded stock it now is.
    adopted = stock_template_id is None
    if adopted:
        stock_template_id = await _adopt_card_async(
            db,
            doc,
            line,
            item,
            user_id=user_id,
            unit_confirmed_over_template=unit_confirmed_over_template,
        )
        line.product_template_id = stock_template_id
        await db.flush()
        # The card is the record's now, and so is the shelf it stands on: the
        # stock it already held was never in the register, and every write
        # below treats the row as carded stock. Posting the opening here is
        # what keeps the pair (card, location) saying one number.
        await _post_opening_balance_async(
            db,
            doc,
            user_id=user_id,
            item=item,
            template_id=stock_template_id,
            location_id=item.location_id or doc.source_location_id,
        )
    # The line may name the supplier's unit; the shelf is kept in the
    # product's. Converted once here, so the record and the movement
    # cannot disagree about what the number means.
    executed_quantity = await core_api.uoms.to_stock_uom_async(
        db, doc.organization_id, stock_template_id, executed_quantity, line.uom_id
    )
    # The source comes first here — this is where the door takes from, not
    # where the record stands — the reverse of the opening balance above.
    # The two orders would disagree only with both shelves named and
    # different, and confirmation refuses that document before it gets here.
    dispatch_location = line_source_shelf(line, doc, item)
    await _require_stock_at(
        db,
        doc,
        item=item,
        quantity=executed_quantity,
        template_id=stock_template_id,
        location_id=dispatch_location,
    )
    lot_id = await _resolve_lot(db, doc, line, create_if_missing=False)
    consumed = await _take_the_line_off_the_records(
        db,
        doc,
        line,
        item=item,
        stock_template_id=stock_template_id,
        location_id=dispatch_location,
        executed_quantity=executed_quantity,
        lot_id=lot_id,
        user_id=user_id,
    )
    if line.source_location_id is not None:
        # A line pinned from a zone says where its goods went, so a correction
        # of this delivery lands on the same shelf (_correction_landing_location).
        # Written before any split below, which copies it to the siblings.
        line.executed_location_id = dispatch_location
    # What the line took, per line it now stands on: a date split below hands
    # the goods to siblings, and each is valued by what it took.
    taken_by_line = [(line, executed_quantity)]
    lots = (
        await core_api.stock.list_lots_async(db, doc.organization_id, stock_template_id)
        if consumed
        else []
    )
    if lot_id is None and consumed:
        taken_by_line = await _split_line_by_goods_taken(
            db, doc, line, consumed, {lot.id: lot for lot in lots}
        )
    elif lot_id is not None and consumed:
        # A line that names its batch says the date of that batch.
        line.expiry_date = next(
            (lot.expiry_date for lot in lots if lot.id == lot_id), line.expiry_date
        )
    if stock_template_id and dispatch_location:
        for taken_line, taken_quantity in taken_by_line:
            await core_api.valuation.record_delivery_async(
                db,
                doc.organization_id,
                stock_template_id,
                taken_quantity,
                document_line_id=taken_line.id,
                # A return to the supplier is a dispatch by type and a
                # reversal by nature: the goods leave off the delivery they
                # arrived on, at that delivery's price. An ordinary dispatch
                # names no such line and drains plain FIFO.
                reverses_line_id=taken_line.corrects_line_id,
            )


async def _split_line_by_goods_taken(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    consumed: list[QuantConsumptionDTO],
    batches: dict[UUID, Any],
) -> list[tuple[DocumentLine, Decimal]]:
    """Stand a line that named no batch on one line per date and batch it took.

    A line that names no batch is told apart by what it took: stock with no
    batch by its date, a batch by its name and its own date. The line says
    which left, and is split where the draw crossed any of them. Answers
    every line the goods now stand on with what it took.
    """
    by_part: dict[tuple[UUID | None, date | None], tuple[Decimal, UUID | None]] = {}
    for c in consumed:
        batch = batches.get(c.lot_id) if c.lot_id else None
        part = (c.lot_id, batch.expiry_date if batch else c.expiry_date)
        quantity, record = by_part.get(part, (Decimal('0'), None))
        by_part[part] = (quantity + c.consumed, record or c.record_id)
    return await date_line_by_goods_taken_async(
        db,
        doc,
        line,
        [
            (day, quantity, record, batches[batch_id].name if batch_id else None)
            for (batch_id, day), (quantity, record) in by_part.items()
        ],
    )


async def scrap_item(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    user_id: UUID,
    *,
    unit_confirmed_over_template: bool = False,
) -> None:
    """Scrap: take the goods off the shelf, then decrement the record.

    The record used to be optional here. A line naming only a product left
    both the record and — with no source location on the document — the shelf
    unresolved, so the whole stock block was skipped and the document closed
    as COMPLETED anyway. The register then said a jar of honey had been
    written off while the jar stood on the shelf. A dispatch in the same
    position refuses, and so does this now.
    """
    executed_quantity = _executed_quantity(line)
    if not line.item_id:
        raise ServiceRejectionError('document_scrap_lines_reference_items')
    item = await _get_item_or_raise(db, doc.organization_id, line.item_id)

    stock_template_id = line.product_template_id or (item.template_id if item else None)
    # A record that predates its card holds its stock outside the ledger —
    # and this door's ledger writes were gated on the very id such a row
    # does not have, so the goods left the record while the register read
    # empty. The card comes first, the same adoption the receipt runs, and
    # the block below treats the row as the carded stock it now is.
    adopted = stock_template_id is None
    if adopted:
        stock_template_id = await _adopt_card_async(
            db,
            doc,
            line,
            item,
            user_id=user_id,
            unit_confirmed_over_template=unit_confirmed_over_template,
        )
        line.product_template_id = stock_template_id
        await db.flush()
        # The card is the record's now, and so is the shelf it stands on: the
        # stock it already held was never in the register, so the write-off
        # below would take off a shelf that reads empty and leave the pair
        # (card, location) saying two different numbers about it. Posting the
        # opening first makes this a write-off of stock the register knows.
        await _post_opening_balance_async(
            db,
            doc,
            user_id=user_id,
            item=item,
            template_id=stock_template_id,
            location_id=item.location_id or doc.source_location_id,
        )
    # The line may name the supplier's unit; the shelf is kept in the
    # product's. Converted once here, so the record and the movement
    # cannot disagree about what the number means.
    executed_quantity = await core_api.uoms.to_stock_uom_async(
        db, doc.organization_id, stock_template_id, executed_quantity, line.uom_id
    )
    # The source comes first — this is where the door takes from, the
    # reverse of the opening balance above; confirmation has already
    # refused the one document where the two would disagree.
    scrap_location = line_source_shelf(line, doc, item)

    # verify stock sufficiency BEFORE the cost layer and the records are drawn.
    # Previously this check ran after the quant was already decremented, so an
    # insufficient scrap could drive the quant negative before raising.
    await _require_stock_at(
        db,
        doc,
        item=item,
        quantity=executed_quantity,
        template_id=stock_template_id,
        location_id=scrap_location,
    )
    lot_id = await _resolve_lot(db, doc, line, create_if_missing=False)
    consumed = await _take_the_line_off_the_records(
        db,
        doc,
        line,
        item=item,
        stock_template_id=stock_template_id,
        location_id=scrap_location,
        executed_quantity=executed_quantity,
        # The operator chose the batch, whatever state it is in now. Scrapping
        # is the one thing you are supposed to do with a recalled batch, and
        # sending it through the consumption guard meant releasing the batch
        # first, which erased the recall. A disposal is not a consumption:
        # a batch confirmed good and recalled before the write-off still
        # leaves by its name, where the strategy branch keeps skipping
        # everything held back, so no scrap ever reaches quarantined stock
        # by accident.
        lot_id=lot_id,
        user_id=user_id,
        require_active_lot=False,
    )
    taken_by_line = [(line, executed_quantity)]
    if lot_id is None and consumed:
        # A write-off that drew across batches stands on one line per batch,
        # so its undo puts each one back instead of one batchless quantity.
        lots = await core_api.stock.list_lots_async(
            db, doc.organization_id, stock_template_id
        )
        taken_by_line = await _split_line_by_goods_taken(
            db, doc, line, consumed, {lot.id: lot for lot in lots}
        )
    if stock_template_id and scrap_location:
        for taken_line, taken_quantity in taken_by_line:
            # A scrapping is a disposal, and the waste report is entitled to see
            # it. A dispatch, a few functions up, is neither a use nor a waste —
            # those goods went where they were sold to — so it names no reason.
            cost = await core_api.valuation.record_delivery_async(
                db,
                doc.organization_id,
                stock_template_id,
                taken_quantity,
                document_line_id=taken_line.id,
                reason=ItemAction.DISPOSED.value,
            )
            # What the loss cost: the layers the write-off drew, not a price
            # somebody typed. A line the layers could not value stays unvalued
            # rather than carrying a plan figure, and the document total then
            # counts it as missing instead of as zero.
            value = quantise(cost) if cost is not None else None
            taken_line.line_value = value
            taken_line.line_tax = None
            taken_line.line_gross = value
