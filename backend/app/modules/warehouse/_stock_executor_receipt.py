from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    ItemCreateDTO,
    RecordPostDTO,
    UserContextDTO,
)
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._receipt_planning import ReceiptLocationPlanner
from ._stock_executor_helpers import (
    _adopt_card_async,
    _base_history,
    _executed_quantity,
    _get_item_or_raise,
    _locked_quantity,
    _post_opening_balance_async,
    _resolve_lot,
)
from .document_profile_service import get_profile
from .models import Document, DocumentLine


async def _template_for_new_row(
    db: AsyncSession,
    doc: Document,
    template_id: UUID | None,
) -> Any:
    """The product a record about to be opened is a record *of*.

    Read only when a record has to be opened — a line topping up one that
    already stands here has no use for it.
    """
    if template_id is None:
        return None
    template = await core_api.product_templates.get_async(
        db, doc.organization_id, template_id
    )
    if not template:
        raise ServiceRejectionError('stock_product_not_found', product=template_id)
    return template


async def _stock_row_at(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    *,
    stock_template_id: UUID,
    location_id: UUID,
    lot_id: UUID | None,
) -> Any:
    """Point the delivery at the record it tops up on this shelf, if any.

    A line that names a product rather than a record used to go straight to
    ``items.create``, so a catalogued product could be received exactly once:
    with a barcode the second delivery broke ``uq_items_org_barcode_active``
    and the endpoint answered 500, and without one the catalogue quietly grew
    a second row holding half the stock.

    The place is part of the question. Asking it organization-wide answered
    with whichever row was oldest, so a delivery steered to Floor 1 topped up
    a row standing in Dry Goods while the movement went to Floor 1 — the ledger,
    the catalogue and the document each naming a different shelf.

    The batch is part of it too: a record holds one batch, so a delivery of
    another batch to the same shelf is another record.
    """
    return await core_api.items.find_stock_row_async(
        db,
        doc.organization_id,
        barcode=line.barcode,
        template_id=stock_template_id,
        expiry_date=line.expiry_date,
        storage_location_id=location_id,
        lot_id=lot_id,
        # The delivery writes this record's number next; found under the lock,
        # it is not locked again.
        for_update=True,
    )


async def _row_for_receipt_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    *,
    named: Any,
    stock_template_id: UUID,
    receive_location: UUID,
) -> tuple[Any, UUID | None]:
    """The record a delivery tops up, and the batch it belongs to.

    The card first, settled onto a line that only named a record: the batch
    is read second, and ``_resolve_lot`` reads the line's card. The record
    last: one that stands where this delivery lands and holds this batch
    takes it; any other batch is another record, because a record holds one
    batch. That includes the record the line names: one that had no card a
    moment ago was given one before this and holds goods of no batch, so a
    delivery of a batch opens a record of its own beside it rather than
    naming the old stock with a batch it never came in.
    """
    if line.product_template_id is None:
        line.product_template_id = stock_template_id
    lot_id = await _resolve_lot(db, doc, line)
    named_takes_it = (
        named is not None
        and named.location_id == receive_location
        and named.lot_id == lot_id
    )
    row = (
        named
        if named_takes_it
        else await _stock_row_at(
            db,
            doc,
            line,
            stock_template_id=stock_template_id,
            location_id=receive_location,
            lot_id=lot_id,
        )
    )
    return row, lot_id


async def _open_received_row(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    user_id: UUID,
    *,
    template: Any,
    location_id: UUID,
    quantity: Decimal,
    history: dict[str, Any],
    named: Any = None,
    lot_id: UUID | None = None,
) -> Any:
    """Open a record of *template* for goods arriving where none stands.

    A line naming an existing record that stands on another shelf — the
    worker sent this delivery to a shelf of its own choosing — files the new
    record where that one is filed: the goods are the same product, the
    shelf is new.

    Every line arrives with a card. A receipt refuses, at confirmation and
    again at posting, a line that names no record, no product and no code
    the catalogue knows; a named record that had no card is given one before
    the delivery is weighed. The words of a hand-typed line therefore never
    open a record of their own here.
    """
    # Where the new record is filed: one rule for every executor that opens
    # a record from goods it moves or takes in. The record the line named
    # answers first — the identity this opener borrows is its — and with
    # none, the category the product's records carry. The rule lives in the
    # items service, so the receipt, the transfer's remainder and a
    # production run's output answer alike.
    category_id = await core_api.items.inherited_category_async(
        db,
        doc.organization_id,
        source_category_id=named.category_id if named is not None else None,
        template_id=template.id,
    )
    # The card's "purchase price per unit" and the fallback value for an
    # organization without cost layers. The layer posted by the caller is
    # still what the stock is worth; this is what the document said, kept
    # where a person will look for it. A record is denominated in the
    # organization's money, so a price stated in another currency stays on
    # the layer only — the record cannot carry it honestly.
    organization = await core_api.organizations.get_async(db, doc.organization_id)
    price_currency = line.currency or doc.currency
    stated_price = (
        line.unit_price
        if organization is None or price_currency in (None, organization.currency)
        else None
    )
    return await core_api.items.create_async(
        db,
        doc.organization_id,
        ItemCreateDTO(
            name=template.name,
            brand=template.brand,
            # The template owns the barcode. A record backed by one is
            # identified through it, and leaves the barcode free for the
            # record holding the same product on the next shelf —
            # ``uq_items_org_barcode_active`` allows only one bearer.
            barcode=None,
            location_id=location_id,
            quantity=quantity,
            # The quantity has already been converted into the product's
            # stock unit, so the record has to say that unit — carrying
            # the line's would relabel the number without changing it.
            uom_id=template.uom_id or line.uom_id,
            expiry_date=line.expiry_date,
            template_id=template.id,
            category_id=category_id,
            image_url=template.image_url,
            description=template.description,
            purchase_price=stated_price,
            lot_id=lot_id,
        ),
        user=UserContextDTO(id=user_id, organization_id=doc.organization_id),
        source_document_id=doc.id,
        history_changes={**history, 'from_template': str(template.id)},
        post_the_change=False,
    )


async def _the_number_the_delivery_lands_on(
    db: AsyncSession,
    doc: Document,
    row: Any,
    executed_quantity: Decimal,
    history: dict[str, Any],
) -> tuple[Decimal, list[RecordPostDTO]]:
    """What the found record says once this delivery lands, as a record post.

    Found without a lock, so what the record holds is asked again under one:
    two receipts that both read the record before either wrote it used to
    write the same sum, and one delivery left the record but not the ledger.
    The number goes back as a :class:`RecordPostDTO` — the movement pass
    states it inside the stock's locks, where the movement is written, so
    one operation is one transition of the record and its ledger, not a
    record changed here and a ledger settled there.
    """
    old_qty = await _locked_quantity(db, doc, row.id)
    return old_qty, [
        RecordPostDTO(
            item_id=row.id,
            new_quantity=old_qty + executed_quantity,
            history=history,
            source_document_id=doc.id,
        )
    ]


async def _note_a_rule_the_delivery_ignored(
    db: AsyncSession,
    planner: ReceiptLocationPlanner,
    decision: Any,
    receive_location: UUID,
    history: dict[str, Any],
) -> None:
    """Landing somewhere the rule did not point is a decision, not a detail.

    The journal keeps both shelves, so a move away from the rule reads as
    what it was instead of only showing its result.
    """
    if decision.rule_target_location_id is None:
        return
    if decision.rule_target_location_id == receive_location:
        return
    history['rule_location'] = decision.rule_target_name or str(
        decision.rule_target_location_id
    )
    history['landed_location'] = await planner.location_name(receive_location) or str(
        receive_location
    )


async def _quarantine_shelf_async(db: AsyncSession, doc: Document) -> UUID:
    """The shelf goods held back are put on: the one the profile names.

    A receipt line coded DAMAGE or QUALITY_HOLD that names no batch has
    nothing to hold back in place, so it is booked onto this shelf instead
    of the one the putaway decision would have picked. With none named the
    receipt is refused: the alternative is the old behaviour, goods that
    were declared unfit landing among those a picking can draw.
    """
    profile = await get_profile(db, doc.organization_id)
    if profile is None or profile.quarantine_location_id is None:
        raise ServiceRejectionError('receipt_needs_quarantine_location')
    return cast('UUID', profile.quarantine_location_id)


async def _reserve_the_held_goods_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    *,
    stock_template_id: UUID,
    location_id: UUID,
    quantity: Decimal,
    user_id: UUID,
) -> None:
    """Hold a batchless quantity back from every draw, not only from the plan.

    A named batch is held by its status: picking, every draw and every
    reservation asks the lot before it touches the goods. Goods held on the
    quarantine shelf have no batch to ask, so the shelf itself was the hold
    and that only bound the doors that read the profile — an ordinary
    dispatch that named the shelf took the goods, and nothing in the stock
    view said they were not free. The quantity is reserved against the
    receipt here instead, so the view counts it as reserved rather than
    available, a picker is never sent to it, and a document that asks the
    shelf for more than its free part is refused. A transfer that carries
    the goods off the quarantine shelf releases the hold; nothing else
    consumes it.
    """
    result = await core_api.stock.reserve_for_document_async(
        db,
        doc.organization_id,
        stock_template_id,
        location_id,
        quantity,
        document_id=doc.id,
        document_line_id=line.id,
    )
    if not result.success:
        # The goods were just booked onto this shelf under its anchor, so the
        # only way the hold cannot be taken is stock there another hold has
        # already claimed. Refuse rather than book goods every draw could
        # take.
        raise ServiceRejectionError('stock_reserved_over_quantity')
    await _journal_the_hold_async(db, doc, line, user_id)


async def _journal_the_hold_async(
    db: AsyncSession, doc: Document, line: DocumentLine, user_id: UUID
) -> None:
    """Say in the audit log how much a receipt held back, and why.

    The goods themselves arrive in the journal as an ordinary new record on
    the quarantine shelf, which says where they went but not that they were
    held or under which code. The reason lives on the document line alone,
    so the row that names the quantity and the code is written here, beside
    the document, in the same transaction as the hold.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=doc.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'product_name': line.name,
            'held_quantity': str(line.held_quantity),
            'discrepancy_code': line.discrepancy_code,
            'discrepancy_reason': line.discrepancy_reason,
        },
    )


async def _hold_the_batch_back_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    lot_id: UUID,
    user_id: UUID,
) -> None:
    """Quarantine the batch a held-back line was received under.

    A batch already held, on hold or recalled stays in that state: the
    receipt must not turn a recall into a milder status. The hold is
    journaled either way: the receipt still held that quantity back.
    """
    await _journal_the_hold_async(db, doc, line, user_id)
    lots = await core_api.stock.list_lots_async(
        db, doc.organization_id, line.product_template_id
    )
    if any(lot.id == lot_id and lot.status != 'active' for lot in lots):
        return
    await core_api.stock.set_lot_status_async(
        db,
        doc.organization_id,
        lot_id,
        'quarantined',
        line.discrepancy_reason or line.discrepancy_code,
        user_id=user_id,
    )


async def _land_the_delivery_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    user_id: UUID,
    *,
    named: Any,
    stock_template_id: UUID,
    receive_location: UUID,
    quantity: Decimal,
    history: dict[str, Any],
) -> tuple[Any, UUID | None]:
    """Book one quantity onto one shelf: the record and the movement.

    The record and the movement are two accounts of the same goods — the
    record is the stock and the movement the journal that explains it, and
    the reconciliation report compares the shelf with that journal per
    (template, location). A line whose held quantity is separated from the
    good one is booked in two passes, one per shelf, and each pass has to
    find its own record and state its own movement; sharing this pass is
    what keeps the two halves of one receipt from being written two ways.

    Returns the record that took the quantity and the batch it belongs to.
    """
    row, lot_id = await _row_for_receipt_async(
        db,
        doc,
        line,
        named=named,
        stock_template_id=stock_template_id,
        receive_location=receive_location,
    )

    record_posts: list[RecordPostDTO] = []
    if row is not None:
        _old_qty, record_posts = await _the_number_the_delivery_lands_on(
            db, doc, row, quantity, history
        )
    else:
        row = await _open_received_row(
            db,
            doc,
            line,
            user_id,
            template=await _template_for_new_row(db, doc, stock_template_id),
            location_id=receive_location,
            quantity=quantity,
            history=history,
            named=named,
            lot_id=lot_id,
        )

    line.item_id = row.id
    # Where the goods are, not where the row that answered was standing: for a
    # record that owns its barcode there is exactly one row and no group
    # beside it, so the delivery lands with it rather than at the document's
    # target.
    landed_location = row.location_id
    line.executed_location_id = landed_location
    await db.flush()

    await core_api.stock.post_movement_async(
        db,
        doc.organization_id,
        stock_template_id,
        quantity,
        to_location_id=landed_location,
        lot_id=lot_id,
        reference_type='document',
        reference_id=doc.id,
        created_by=user_id,
        records=record_posts,
    )
    return row, lot_id


async def _receive_item(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    user_id: UUID,
    surcharge: Decimal = Decimal('0'),
    *,
    planner: ReceiptLocationPlanner,
    unit_confirmed_over_template: bool = False,
) -> None:
    """Land one received line: one record, one movement, one shelf.

    The record and the movement are two accounts of the same goods — the
    record is the stock and the movement the journal that explains it, and
    the reconciliation report compares the shelf with that journal per
    (template, location). So the receipt settles *where* before it settles
    *which row*, and both the row it tops up and the movement it writes name
    that one place. The line then says so: ``executed_location_id`` is where
    the goods actually went, which is not always where the document asked
    for them.
    """
    executed_quantity = _executed_quantity(line)
    history = _base_history(doc)

    named = (
        await _get_item_or_raise(db, doc.organization_id, line.item_id, lock=True)
        if line.item_id
        else None
    )
    # The card every write below is keyed by. A receipt line names a product
    # or a record by the time it is posted (``_require_products_on_receipt_lines``
    # refuses any other at confirmation and at posting), so the card is the
    # line's own, the record's, or the one the record adopts just below.
    # Declared, because the row it may be read from is untyped: a value of
    # type ``Any`` assigned to an inferred variable widens it back to
    # ``UUID | None``.
    stock_template_id: UUID | None = line.product_template_id or (
        named.template_id if named is not None else None
    )

    # A record that predates its card holds its stock in a unit only the card
    # can name, and the conversion below asks it. The card used to be adopted
    # after the delivery had been written to the record, so the sum happened
    # across two units — 4 g of stock plus a 2 kg delivery read as 6 — while
    # the shelf took the grams. The card comes first.
    if stock_template_id is None:
        if named is None:
            raise ServiceRejectionError('document_line_needs_identity')
        adopted_id = await _adopt_card_async(
            db,
            doc,
            line,
            named,
            user_id=user_id,
            unit_confirmed_over_template=unit_confirmed_over_template,
        )
        if adopted_id is None:
            raise ServiceRejectionError('item_not_found')
        stock_template_id = adopted_id
        # Joining the ledger says what the record held before this delivery,
        # at the record's own shelf — the place the report counts that stock
        # under, which is not always where this delivery lands. The record has
        # not been topped up yet, so the holding is read as it stands.
        await _post_opening_balance_async(
            db,
            doc,
            user_id=user_id,
            item=named,
            template_id=stock_template_id,
            location_id=named.location_id,
        )

    lot_named = line.serial_number or line.batch_number

    # The document speaks the supplier's unit; the shelf speaks the
    # product's. Converted once, here, so the record, the movement and the
    # valuation cannot end up disagreeing about what the number
    # means — which they did, because none of them ever asked.
    executed_quantity = await core_api.uoms.to_stock_uom_async(
        db, doc.organization_id, stock_template_id, executed_quantity, line.uom_id
    )

    # One decision for preview and execution alike: the planner holds the
    # rules loaded once for the whole document and answers with where the
    # goods land and who decided it.
    decision = await planner.decide(
        named=named,
        stock_template_id=stock_template_id,
        line_target_id=line.target_location_id,
        quantity_stock=executed_quantity,
    )
    # A warehouse that receives in two steps books the goods into its
    # receiving area; the decision is then what the putaway task suggests.
    receive_location = planner.landing(decision)
    if receive_location is None:
        raise ServiceRejectionError('receipt_needs_target_location')
    await _note_a_rule_the_delivery_ignored(
        db, planner, decision, receive_location, history
    )

    # What the line received and, of that, what it holds back. The two are
    # booked apart on a line with no batch: the held part is not for the
    # shelf the plan picked, and the good part is. A line naming a batch
    # keeps its goods together — one batch is one record — and the whole
    # batch is held back instead.
    held_line_quantity = line.held_quantity or Decimal('0')
    held_quantity = (
        await core_api.uoms.to_stock_uom_async(
            db, doc.organization_id, stock_template_id, held_line_quantity, line.uom_id
        )
        if held_line_quantity > Decimal('0')
        else Decimal('0')
    )
    if held_line_quantity > Decimal('0') and not lot_named:
        quarantine_location = await _quarantine_shelf_async(db, doc)
        good_row = None
        if held_line_quantity < _executed_quantity(line):
            good_row, _lot = await _land_the_delivery_async(
                db,
                doc,
                line,
                user_id,
                named=named,
                stock_template_id=stock_template_id,
                receive_location=receive_location,
                quantity=executed_quantity - held_quantity,
                history=history,
            )
        held_history = _base_history(doc)
        held_history['held_back'] = 'true'
        await _land_the_delivery_async(
            db,
            doc,
            line,
            user_id,
            named=named,
            stock_template_id=stock_template_id,
            receive_location=quarantine_location,
            quantity=held_quantity,
            history=held_history,
        )
        await _reserve_the_held_goods_async(
            db,
            doc,
            line,
            stock_template_id=stock_template_id,
            location_id=quarantine_location,
            quantity=held_quantity,
            user_id=user_id,
        )
        # The line points at the record that holds the good part; a delivery
        # held back in full points at the shelf it is waiting on.
        if good_row is not None:
            line.item_id = good_row.id
            line.executed_location_id = good_row.location_id
        else:
            line.executed_location_id = quarantine_location
    else:
        _row, lot_id = await _land_the_delivery_async(
            db,
            doc,
            line,
            user_id,
            named=named,
            stock_template_id=stock_template_id,
            receive_location=receive_location,
            quantity=executed_quantity,
            history=history,
        )
        if held_line_quantity > Decimal('0') and lot_id is not None:
            await _hold_the_batch_back_async(db, doc, line, lot_id, user_id)
    # The layer covers everything the line brought in, held back or not: the
    # goods exist and carry the supplier's cost, wherever they are waiting.
    await _record_receipt_valuation(
        db, doc, line, stock_template_id, executed_quantity, surcharge
    )


async def _record_receipt_valuation(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    product_template_id: UUID,
    stock_quantity: Decimal,
    surcharge: Decimal = Decimal('0'),
) -> None:
    """Post the receipt layer, in the unit the stock is kept in.

    *stock_quantity* is the line quantity already converted. The price on the
    line is per line unit, so the layer's unit cost is the line's total value
    spread over the converted quantity — 500 g at 0.02 is 10.00 for half a
    kilogram, not 0.02 per kilogram.
    """
    # A line with no price used to post no layer at all, so the goods reached
    # the shelf and the cost history never heard of them — and nothing looked
    # for that gap, because reconciliation compared records against quants and
    # not against the layers. A receipt is a receipt whether or not somebody
    # typed a price; ``unit_cost=None`` says only that nobody did.
    #
    # Where there is a price it is the supplier's, so the currency is theirs
    # too — the line carries it, the document carries it, and the cost history
    # used to receive neither. A receipt of 100 x 40.10 PLN into an
    # organization keeping USD wrote 40.10 and nothing knew it was złoty.
    unit_cost = line.unit_price
    if unit_cost is not None and stock_quantity > 0:
        line_quantity = _executed_quantity(line)
        if line_quantity != stock_quantity:
            unit_cost = (line_quantity * unit_cost) / stock_quantity
    # This line's share of the freight, duty and insurance the delivery
    # arrived with. Without it the shelf is worth what the supplier invoiced
    # and nothing else, and every margin taken off that number is short by
    # the cost of getting the goods there. A line nobody priced still gets
    # its share, but on top of the cost an unpriced line has - the
    # organization's rate, or none - so the share never makes the layer look
    # like a price the supplier stated.
    extra_unit_cost = (
        surcharge / stock_quantity if surcharge and stock_quantity > 0 else Decimal('0')
    )
    await core_api.valuation.record_receipt_async(
        db,
        doc.organization_id,
        product_template_id,
        stock_quantity,
        unit_cost,
        document_line_id=line.id,
        currency=line.currency or doc.currency,
        # The receipt's business date (FIFO consumes in business-date
        # order, not in booking order) — the document's scheduled date is
        # the one date the document itself states.
        document_date=doc.scheduled_date,
        # A return from the customer is a receipt by type and a reversal
        # by nature: the goods come back at what they cost when they
        # left, not at the price the customer paid for them. An ordinary
        # delivery names no such line and is worth what the supplier asked.
        reverses_line_id=line.corrects_line_id,
        extra_unit_cost=extra_unit_cost,
    )
