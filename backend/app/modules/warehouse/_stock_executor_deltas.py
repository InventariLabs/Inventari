"""Stock executor — signed-delta operations (correction + adjustment).

Extracted from document_stock_executor.py to keep the dispatcher under
the 400-LOC module guideline. Both apply a signed done_quantity delta as
one movement pass (single named grain, post_movement_async) with the lot
resolved from the document line.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import RecordPostDTO
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from ._stock_executor_helpers import (
    _adopt_card_async,
    _base_history,
    _get_correction_item_or_raise,
    _get_item_or_raise,
    _locked_quantity,
    _post_opening_balance_async,
    _resolve_lot,
    line_source_shelf,
)
from .models import Document, DocumentLine


async def _move_delta_at(
    db: AsyncSession,
    doc: Document,
    user_id: UUID,
    *,
    template_id: UUID,
    location_id: UUID,
    delta: Decimal,
    lot_id: UUID | None,
    owner_id: UUID | None,
    record_posts: list[RecordPostDTO],
) -> None:
    """Apply a signed delta to one location's stock, and record the move.

    The movement and the records named on this pass have to agree about
    direction, so the sign is read once, here, rather than three times in
    the branches that used to spell this out: a transfer correction's two
    sides and a plain one's.

    A correction restates one named grain — the batch-less one too, when the
    original line named no batch — and the movement takes exactly that
    grain; a removal strategy would pick and could correct a batch the
    original never touched. The first call of a transfer correction carries
    the record posts, so the record is stated once, inside the stock's
    locks.
    """
    await core_api.stock.post_movement_async(
        db,
        doc.organization_id,
        template_id,
        abs(delta),
        from_location_id=location_id if delta < 0 else None,
        to_location_id=location_id if delta > 0 else None,
        lot_id=lot_id,
        owner_id=owner_id,
        require_active_lot=False,
        reference_type='document',
        reference_id=doc.id,
        created_by=user_id,
        records=record_posts,
    )
    # The record posts ride the first pass only: the record is stated once,
    # whatever number of grains the correction restates.
    record_posts.clear()


def _correction_landing_location(
    original_type: str,
    doc: Document,
    item_location: UUID | None,
    *,
    original_line: DocumentLine | None = None,
) -> UUID | None:
    """Where a correction of *original_type* lands its delta.

    Where the original happened, not where the record's shelf is now —
    the correction rewrites what that original did, so it happens where the
    original did it. The door that executed the original recorded that place
    in ``executed_location_id``, and it is not always the document's location:
    a receipt lands the goods with the record it tops up, and its own docstring
    says so. Reading the document's target instead put a correction's stock on
    a shelf the delivery never touched, and the reconciliation report named
    drift nobody caused: that report pairs, per (card, shelf), the shelf the
    records make against the movement ledger, so a delta landed elsewhere
    moved the ledger without the record, and the record's shelf read 12
    where it held 10.

    The document's own location stays the answer for doors that record no
    executed place (dispatches, scrap, transfers), and for documents seeded
    before the column existed.
    """
    landed = original_line.executed_location_id if original_line else None
    if dt.is_receipt(original_type):
        return landed or doc.target_location_id or item_location
    if dt.is_dispatch(original_type):
        return landed or doc.source_location_id or item_location
    return landed or item_location


async def _lock_what_the_lines_change(
    db: AsyncSession, doc: Document, original: Document, sign: int
) -> None:
    """Lock the records of the lines that change stock, and the cost layers they draw.

    Together before the first line is read; each line's own request for its
    record, and each removal's for its layers, is then answered from what is
    held. A line that names no record is refused where it is walked.
    """
    changing = [line for line in doc.lines if line.done_quantity != Decimal('0')]
    await core_api.items.lock_records_async(
        db, doc.organization_id, [line.item_id for line in changing if line.item_id]
    )
    if not dt.is_transfer(original.type):
        # A transfer correction leaves the cost basis alone.
        await core_api.valuation.lock_open_layers_async(
            db,
            doc.organization_id,
            [
                line.product_template_id
                for line in changing
                if line.product_template_id and sign * line.done_quantity < 0
            ],
        )


async def execute_correction(
    db: AsyncSession,
    doc: Document,
    user_id: UUID,
    *,
    unit_confirmed_over_template: bool = False,
) -> None:
    """Apply CORRECTION: signed delta against an original document's stock effect."""
    # Corrections restate a single named grain on the movement pass, with
    # the lot resolved from the original document line,
    # so cross-lot FEFO/FIFO is not applied here. Acceptable for now because
    # corrections target a specific known lot; revisit if corrections ever
    # need to span multiple unlabeled lots.
    if not doc.corrects_document_id:
        raise ServiceRejectionError('document_correction_missing_original')

    result = await db.execute(
        select(Document).where(
            Document.id == doc.corrects_document_id,
            Document.organization_id == doc.organization_id,
        )
    )
    original = result.scalars().first()
    if not original:
        raise ServiceRejectionError(
            'document_correction_original_not_found',
            document=doc.corrects_document_id,
        )

    # Corrections of receipts/transfers apply delta directly; corrections of
    # dispatches invert it. A single sign multiplier collapses all branches.
    sign = dt.correction_sign(original.type)

    # The line each corrected line restates, by id: a correction lands where
    # that line landed, and a document's target is not the same thing.
    original_lines_by_id = {line.id: line for line in original.lines}

    # The same reason every other document door writes. A correction used to
    # spell its own dict and left the reason out, so its quantity row read as
    # a manual edit beside the receipt rows that carry one.
    history_base = {
        **_base_history(doc),
        'corrects_document_number': original.number,
    }

    await _lock_what_the_lines_change(db, doc, original, sign)

    for line in doc.lines:
        delta = line.done_quantity
        if delta == Decimal('0'):
            # Nothing to correct on this line — the usual case for the lines
            # of the original the correction leaves alone.
            continue
        if not line.item_id:
            # This used to be skipped alongside the zero deltas, so a
            # correction could report itself applied while one of its lines
            # moved nothing.
            raise ServiceRejectionError('document_correction_lines_reference_items')

        # name the product in the failure instead of echoing the raw
        # item UUID — the message reaches the user through the API error toast.
        item = await _get_correction_item_or_raise(db, doc.organization_id, line)
        original_line = (
            original_lines_by_id.get(line.corrects_line_id)
            if line.corrects_line_id
            else None
        )

        stock_template_id = line.product_template_id or item.template_id
        # A record that predates its card holds its stock outside the ledger,
        # and this door's ledger writes were gated on the very id such a row
        # does not have: the correction drifted off the record while the
        # register read empty. The card comes first — the same adoption the
        # receipt and the outbound doors run — and the block below treats the
        # row as the carded stock it now is.
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
            # The card is the record's now, and so is the shelf it stands on:
            # the count it already held was never in the register. The opening
            # is posted at the record's home — the shelf the report counts the
            # item side under — or, for a record that names none, where this
            # correction is about to land its delta.
            await _post_opening_balance_async(
                db,
                doc,
                user_id=user_id,
                item=item,
                template_id=stock_template_id,
                location_id=item.location_id
                or _correction_landing_location(
                    original.type,
                    doc,
                    item.location_id,
                    original_line=original_line,
                ),
            )
        # A correction inherits the unit of the line it corrects, and every
        # other executor converts before it writes. This one did not, so
        # taking back 500 g of a product kept in kilograms took back 500 kg —
        # off the record and off the ledger at once.
        delta = await core_api.uoms.to_stock_uom_async(
            db, doc.organization_id, stock_template_id, delta, line.uom_id
        )
        effective_delta = sign * delta
        old_qty = await _locked_quantity(db, doc, item.id)
        new_qty = old_qty + effective_delta

        if new_qty < 0:
            raise ServiceRejectionError(
                'document_correction_would_go_negative',
                item=line.item_id,
                current=old_qty,
                delta=delta,
                result=new_qty,
            )
        # The batch the line names — copied from the line it corrects — and
        # without one the record's own: the record holds one batch, and a
        # correction that named none used to change the batch-less stock
        # under a record that has one.
        lot_id = (
            await _resolve_lot(db, doc, line, create_if_missing=False) or item.lot_id
        )
        # The record's number rides the movement pass below, stated inside
        # the stock's locks, where the movement is written.
        record_posts = [
            RecordPostDTO(
                item_id=line.item_id,
                new_quantity=new_qty,
                history=history_base,
                source_document_id=doc.id,
            )
        ]

        if stock_template_id:
            is_int = dt.is_transfer(original.type)
            if is_int:
                # INT corrections rebalance both the source and the target.
                if doc.target_location_id:
                    await _move_delta_at(
                        db,
                        doc,
                        user_id,
                        template_id=stock_template_id,
                        location_id=doc.target_location_id,
                        delta=effective_delta,
                        lot_id=lot_id,
                        owner_id=item.owner_id,
                        record_posts=record_posts,
                    )
                # The shelf the original transfer took from: a line pinned from
                # a zone reversed where it was pinned.
                source_shelf = line_source_shelf(original_line or line, doc, item)
                if source_shelf is not None:
                    await _move_delta_at(
                        db,
                        doc,
                        user_id,
                        template_id=stock_template_id,
                        location_id=source_shelf,
                        delta=-effective_delta,
                        lot_id=lot_id,
                        owner_id=item.owner_id,
                        record_posts=record_posts,
                    )
            else:
                correction_location = _correction_landing_location(
                    original.type,
                    doc,
                    item.location_id,
                    original_line=original_line,
                )
                if correction_location:
                    await _move_delta_at(
                        db,
                        doc,
                        user_id,
                        template_id=stock_template_id,
                        location_id=correction_location,
                        delta=effective_delta,
                        lot_id=lot_id,
                        owner_id=item.owner_id,
                        record_posts=record_posts,
                    )

            # SVL is per-template. Skip for INT — transfers don't touch cost basis
            # (a transfer correction moves stock between locations, net zero).
            if not is_int:
                if effective_delta > 0:
                    await core_api.valuation.record_receipt_async(
                        db,
                        doc.organization_id,
                        stock_template_id,
                        effective_delta,
                        # No price is the unpriced policy, not a zero.
                        line.unit_price,
                        document_line_id=line.id,
                        currency=line.currency or doc.currency,
                        # Goods coming back onto the shelf because a dispatch
                        # was overstated come back at what they cost when
                        # they left, not at the sales price on the line. A
                        # receipt corrected upwards names a receipt line,
                        # which posted no outflow, and keeps its price.
                        reverses_line_id=line.corrects_line_id,
                    )
                else:
                    await core_api.valuation.record_delivery_async(
                        db,
                        doc.organization_id,
                        stock_template_id,
                        abs(effective_delta),
                        document_line_id=line.id,
                        # The goods go back off the delivery they came in on,
                        # at that delivery's price — not off whichever layer
                        # in the warehouse happens to be oldest.
                        reverses_line_id=line.corrects_line_id,
                    )


async def execute_adjustment(
    db: AsyncSession,
    doc: Document,
    user_id: UUID,
    *,
    unit_confirmed_over_template: bool = False,
) -> None:
    """Apply ADJUSTMENT: positive/negative delta to item quantity at item's location."""
    # Adjustments restate a single named grain on the movement pass, with
    # the lot resolved from the document line.
    # Acceptable because adjustments target a specific known lot; revisit
    # if adjustments ever need to span multiple unlabeled lots.
    for line in doc.lines:
        delta = line.done_quantity
        if delta == Decimal('0'):
            continue

        if not line.item_id:
            raise ServiceRejectionError('document_adjustment_lines_reference_items')

        item = await _get_item_or_raise(db, doc.organization_id, line.item_id)

        stock_template_id = line.product_template_id or item.template_id
        # A record that predates its card holds its stock outside the ledger,
        # and this door's ledger writes were gated on the very id such a row
        # does not have: the count drifted off the record while the register
        # read empty. The card comes first — the same adoption the receipt and
        # the outbound doors run — and the block below treats the row as the
        # carded stock it now is.
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
            # The card is the record's now, and so is the shelf it stands on:
            # the count it already held was never in the register. The opening
            # is posted on the very shelf the delta below lands on, so the
            # pair (card, location) keeps saying one number.
            await _post_opening_balance_async(
                db,
                doc,
                user_id=user_id,
                item=item,
                template_id=stock_template_id,
                location_id=item.location_id,
            )
        # The shelf is kept in the product's unit; the line may be written in
        # whatever the person counting had to hand.
        delta = await core_api.uoms.to_stock_uom_async(
            db, doc.organization_id, stock_template_id, delta, line.uom_id
        )
        old_qty = await _locked_quantity(db, doc, item.id)
        new_qty = old_qty + delta

        if new_qty < 0:
            raise ServiceRejectionError(
                'document_adjustment_would_go_negative',
                item=line.item_id,
                current=old_qty,
                delta=delta,
                result=new_qty,
            )
        # See the correction above: the line's batch, else the record's own.
        lot_id = (
            await _resolve_lot(db, doc, line, create_if_missing=False) or item.lot_id
        )
        record_posts = [
            RecordPostDTO(
                item_id=line.item_id,
                new_quantity=new_qty,
                history=_base_history(doc),
                source_document_id=doc.id,
            )
        ]

        adjust_location = item.location_id
        if stock_template_id and adjust_location:
            # StockMove for the adjustment (sign-dependent), written by
            # the same pass that states the record.
            await _move_delta_at(
                db,
                doc,
                user_id,
                template_id=stock_template_id,
                location_id=adjust_location,
                delta=delta,
                lot_id=lot_id,
                owner_id=item.owner_id,
                record_posts=record_posts,
            )
            # Keep the StockValuationLayer consistent with the stock change.
            # Without this, ADJUSTMENT moved the stock while SVL stayed
            # frozen, corrupting the valuation (understated on positive
            # adjustment, unconsumed layers on negative adjustment).
            if delta > 0:
                if line.unit_price is not None:
                    await core_api.valuation.record_receipt_async(
                        db,
                        doc.organization_id,
                        stock_template_id,
                        delta,
                        line.unit_price,
                        document_line_id=line.id,
                        currency=line.currency or doc.currency,
                    )
                else:
                    await core_api.valuation.record_unpriced_receipt_async(
                        db, doc.organization_id, stock_template_id, delta
                    )
            else:
                await core_api.valuation.record_delivery_async(
                    db,
                    doc.organization_id,
                    stock_template_id,
                    abs(delta),
                    document_line_id=line.id,
                )
