"""Stock executor — transfer (MM) operations.

Extracted from document_stock_executor.py to keep the dispatcher under
the 400-LOC module guideline. The goods that move are the record's: the
batch the line names, or the record's own, with its owner.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemCreateDTO, RecordPostDTO, UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._stock_executor_helpers import (
    _adopt_card_async,
    _base_history,
    _executed_quantity,
    _post_opening_balance_async,
    _release_the_quarantine_hold_async,
    _resolve_lot,
    line_source_shelf,
)
from .models import Document, DocumentLine


async def _split_record_for_partial_line(
    db: AsyncSession,
    doc: Document,
    item: Any,
    executed_quantity: Decimal,
    user_id: UUID,
) -> tuple[UUID | None, list[RecordPostDTO]]:
    """Leave what the line does not name behind, as a record of its own.

    A partial transfer used to move the record whole while the stock moved
    only the line's quantity, and the two books disagreed from that commit
    on. The record now rides with what the line names; the remainder stays
    on the shelf it stood on as a new record with the same card and the
    same goods. The identity fields — barcode, serial number — are not
    copied: they name this record, not the stock in it, and they travel
    with it. A serialized record therefore cannot take a partial line at
    all. What describes the stock does ride: the image, the receipt date
    the rotation analytics read, the freeze date inside meta_data (the
    field's only home since its column was dropped), and the card itself,
    by id — weight and volume live on the card, so the remainder under it
    reads the same ones.

    The number the record rides with is not written here: it goes back as a
    :class:`RecordPostDTO`, and the movement pass below states it inside the
    stock's locks, beside the movement it writes. The remainder record
    is created here — it is identity work, a new record the door opens.

    Returns the shelf the remainder was left on and the record posts to
    carry; the shelf is None, and the posts empty, when the line named the
    whole record.

    A line naming more than the record holds is refused. The record would
    go whole while the movement took the line's full quantity off the
    shelf, and the difference would stay on the shelf's other records,
    which the ledger already counted as gone.
    """
    record_quantity = item.quantity or Decimal('0')
    if executed_quantity > record_quantity:
        raise ServiceRejectionError(
            'transfer_more_than_the_record_holds',
            item_name=item.name,
            available=format(record_quantity.normalize(), 'f'),
            requested=format(executed_quantity.normalize(), 'f'),
        )
    if executed_quantity == record_quantity:
        return None, []
    if item.serial_number:
        raise ServiceRejectionError(
            'transfer_cannot_split_serialized_record',
            serial_number=item.serial_number,
        )
    remainder = record_quantity - executed_quantity
    remainder_location: UUID | None = item.location_id
    record_posts = [
        RecordPostDTO(
            item_id=item.id,
            new_quantity=executed_quantity,
            history=_base_history(doc),
            source_document_id=doc.id,
        )
    ]
    await core_api.items.create_async(
        db,
        doc.organization_id,
        ItemCreateDTO(
            # Named after the card, not after the record; the card itself is
            # carried by id, so the create pipeline cannot answer to the name
            # and file the remainder under a twin (two cards of one name must
            # not answer instead). Identity fields — barcode, serial number —
            # stay with the record.
            name=item.template_name or item.name,
            template_id=item.template_id,
            category_id=item.category_id,
            location_id=remainder_location,
            quantity=remainder,
            uom_id=item.uom_id,
            brand=item.brand,
            expiry_date=item.expiry_date,
            shelf_location=item.shelf_location,
            metadata=dict(item.meta_data) if item.meta_data else None,
            purchase_price=item.purchase_price,
            currency=item.currency,
            # The remainder is the same goods: the batch and owner stay, and
            # so does everything that describes the stock — the image, and
            # the receipt date the rotation analytics read. freeze_date has
            # no field of its own here because it travels inside meta_data
            # (its column is gone); weight and volume belong to the card the
            # remainder stays under, not to the record.
            image_url=item.image_url,
            added_date=item.added_date,
            lot_id=item.lot_id,
            owner_id=item.owner_id,
        ),
        UserContextDTO(id=user_id, organization_id=doc.organization_id),
        source_document_id=doc.id,
        history_changes=_base_history(doc),
        post_the_change=False,
    )
    return remainder_location, record_posts


async def _refuse_a_record_that_left(
    db: AsyncSession, doc: Document, line: DocumentLine, item: Any
) -> None:
    """Refuse a transfer whose record no longer stands on the shelf it leaves.

    The movement takes the goods off the shelf the line takes from — its pin
    when a zone named the document's source, else the document's source. When
    another transfer has carried the record elsewhere since this document
    was confirmed, going on would take off that shelf goods which are not
    there, and move a record that already moved.
    """
    source_id = line_source_shelf(line, doc, item)
    if source_id is None or item.location_id in (None, source_id):
        return
    record_shelf = await core_api.locations.get_async(
        db, doc.organization_id, item.location_id
    )
    document_shelf = await core_api.locations.get_async(
        db, doc.organization_id, source_id
    )
    raise ServiceRejectionError(
        'document_record_stands_elsewhere',
        item_name=item.name,
        record_shelf=record_shelf.name if record_shelf else str(item.location_id),
        document_shelf=document_shelf.name if document_shelf else str(source_id),
    )


async def transfer_item(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    user_id: UUID,
    *,
    unit_confirmed_over_template: bool = False,
) -> None:
    """MM transfer: move the record to the target location, with its movement."""
    if not line.item_id:
        raise ServiceRejectionError('document_transfer_lines_reference_items')
    # Read under the record's own lock, after the stock's. The document loaded
    # the record along with its lines before this transaction waited for the
    # stock, and a transfer that held the stock meanwhile may have split the
    # record or carried it off. Working the remainder out from that earlier
    # number left a second remainder behind: stock nobody had received.
    item = await core_api.items.get_for_update_async(
        db, doc.organization_id, line.item_id
    )
    if item is None:
        raise ServiceRejectionError('stock_record_not_found', item=line.item_id)
    await _refuse_a_record_that_left(db, doc, line, item)
    executed_quantity = _executed_quantity(line)
    stock_template_id = line.product_template_id or item.template_id
    # A record that predates its card holds its stock outside the ledger —
    # and this door's ledger writes were gated on the very id such a row
    # does not have, so the goods changed shelves while the register read
    # empty. The card comes first, the same adoption the receipt runs, and
    # the blocks below treat the row as the carded stock it now is.
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
        # The record was read before the adoption: the snapshot it rides on
        # still says cardless, and a split below would answer to the name and
        # file the remainder under a card of its own. The card the record
        # joined rides the snapshot too.
        item.template_id = stock_template_id
        await db.flush()
        # The card is the record's now, and so is the shelf it stands on: the
        # stock it already held was never in the register, so the move below
        # would take off a shelf that reads empty and put down what the ledger
        # never held. Posting the opening first is what makes this a move of
        # stock the register knows, like any other.
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
    lot_id = await _resolve_lot(db, doc, line, create_if_missing=False)
    # The shelf the record stands on is the one it leaves, whether the
    # document names that shelf or the record carries it. A held batchless
    # receipt reserved its goods there; carrying them off is the release.
    if stock_template_id is not None:
        await _release_the_quarantine_hold_async(
            db,
            doc,
            template_id=stock_template_id,
            shelf_id=item.location_id,
            quantity=executed_quantity,
            lot_id=lot_id if lot_id is not None else item.lot_id,
        )
    # The move below takes from doc.source_location_id — the document's
    # word, the reverse of the opening balance above, which follows the
    # record's own shelf. Confirmation has already refused the one
    # document where the two orders would disagree. The structural check
    # comes before any write: a document without a destination is refused
    # whether or not its line would split.
    if not doc.target_location_id:
        raise ServiceRejectionError('transfer_needs_target_location')
    # A line may name less than the record holds: the record rides with the
    # line's quantity and the rest stays put (see the helper). The shelf the
    # remainder was left on is also the shelf the movement leaves, when the
    # document names no source of its own.
    remainder_location_id, record_posts = await _split_record_for_partial_line(
        db, doc, item, executed_quantity, user_id
    )
    partial = remainder_location_id is not None
    moved_item = await core_api.items.transfer_async(
        db,
        doc.organization_id,
        line.item_id,
        doc.target_location_id,
        user_id=user_id,
        source_document_id=doc.id,
        history_changes=_base_history(doc),
        post_the_change=False,
    )
    if moved_item is None:
        raise ServiceRejectionError('stock_record_not_found', item=line.item_id)

    if stock_template_id is None:
        return
    # One call states the record the line carried and writes the movement
    # from the source to the target: a named lot moves as itself, otherwise
    # the record's own batch does. A hold stops goods from being used, not
    # from being carried — moving a quarantined batch into a quarantine area
    # is the point of having one — so the named lot is not asked to be
    # active.
    #
    # A transfer that names no source shelf receives at the target: the
    # batch it names lands there with the movement in that says so. It used
    # to raise the quant and write no movement at all. A partial line has a
    # shelf it leaves either way — the one the remainder stands on.
    from_location_id = line.source_location_id or doc.source_location_id
    if partial and from_location_id is None:
        from_location_id = remainder_location_id
    if from_location_id is None and lot_id is None:
        return
    await _carry_the_records_stock(
        db,
        doc,
        item,
        stock_template_id,
        executed_quantity,
        from_location_id=from_location_id,
        lot_id=lot_id,
        user_id=user_id,
        record_posts=record_posts,
    )


async def _carry_the_records_stock(
    db: AsyncSession,
    doc: Document,
    item: Any,
    template_id: UUID,
    quantity: Decimal,
    *,
    from_location_id: UUID | None,
    lot_id: UUID | None,
    user_id: UUID,
    record_posts: list[RecordPostDTO],
) -> None:
    """Move the stock the record holds: its batch and owner, as themselves.

    A batch the line names is the one that moves. Naming none, the record's
    own batch and owner move — the removal strategy would pick by age or
    expiry and carry another batch's stock under this record's name.

    A batch whose records, once the line has left, cannot cover what is
    promised out of it — the rest held for documents already confirmed —
    refuses the transfer: the promise would be left standing on fewer units
    than it holds.

    ``record_posts`` ride the movement that lands: the number the record
    rides with is stated inside the stock's locks, by the pass that writes
    the movement.
    """
    await core_api.stock.post_movement_async(
        db,
        doc.organization_id,
        template_id,
        quantity,
        from_location_id=from_location_id,
        to_location_id=doc.target_location_id,
        lot_id=lot_id if lot_id is not None else item.lot_id,
        owner_id=item.owner_id,
        require_active_lot=False,
        reference_type='document',
        reference_id=doc.id,
        created_by=user_id,
        records=record_posts,
    )
