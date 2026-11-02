from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ServiceRejectionError
from app.core.public_api import core_api

from .models import Document, DocumentLine, DocumentStatus


class CorrectionItemMissingError(AppException):
    """400 — a correction line references an item that no longer exists.

    carries a stable machine code plus the product name in the
       structured detail envelope so clients can render a translated message
       instead of echoing an English sentence. The ``message`` field stays as a
       fallback for API-only consumers.
    """

    def __init__(self, product: str) -> None:
        super().__init__(
            status_code=400,
            code='CORRECTION_ITEM_MISSING',
            message=(
                f'{product} no longer exists in the catalog. This correction '
                'cannot be applied — create a new correction for the current stock.'
            ),
            extra={'product': product},
        )


class RecordUnitMismatchError(AppException):
    """400 — the record being adopted is kept in another unit than its card.

    The bind's refusal, put in the structured envelope a client needs to
    turn into a question: a stable code plus the record's name and both
    units, so the execution screen can offer the confirmation the bind has
    nobody to make on its own. The message stays the bind's own translated
    sentence — read through the catalogue key, in the request's language —
    so API-only consumers keep reading exactly what they read before.
    """

    def __init__(self, product: str, template_unit: str, chosen_unit: str) -> None:
        from app.i18n.service import get_current_lang, get_error_message

        super().__init__(
            status_code=400,
            code='RECORD_UNIT_MISMATCH',
            message=get_error_message(
                'item_unit_differs_from_template_confirmation_required',
                get_current_lang(),
                product=product,
                template_unit=template_unit,
                chosen_unit=chosen_unit,
            ),
            extra={
                'product': product,
                'template_unit': template_unit,
                'chosen_unit': chosen_unit,
            },
        )


def _base_history(doc: Document) -> dict[str, str]:
    """Common history_changes dict shared by all stock operations.

    ``reason`` is what the organization log shows in its own column, beside
    ``stock_take_adjustment`` and ``recipe_picking``. Without it a receipt
    moving a hundred units read as a manual edit: the number and type were
    there, but the log had nothing to say the change came from a document at
    all — and its Detail column is where somebody looks first.
    """
    return {
        'reason': 'document_execution',
        'document_type': doc.type,
        'document_number': doc.number,
    }


async def _get_item_or_raise(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    *,
    lock: bool = False,
) -> Any:
    """Fetch an item via CoreAPI or refuse with a keyed sentence.

    With *lock* the record is taken under its row lock, for a door that is
    about to write its number: the lock is then held when the number is read
    for the write, and is not asked for a second time.
    """
    if lock:
        item = await core_api.items.get_for_update_async(db, org_id, item_id)
    else:
        item = await core_api.items.get_async(db, org_id, item_id)
    if not item:
        raise ServiceRejectionError('stock_record_not_found', item=item_id)
    return item


async def _get_correction_item_or_raise(
    db: AsyncSession, org_id: UUID, line: DocumentLine
) -> Any:
    """Fetch the item a correction line targets, with a structured failure.

    corrections used to fail with a raw ``Item <uuid> not
       found`` sentence that reached the user verbatim. Raise a structured
       ``CORRECTION_ITEM_MISSING`` error carrying the product name instead, so
       the client can render a translated message and the user knows the way out.
    """
    assert line.item_id is not None
    # Under its row lock from the first read: the correction writes this
    # record's number next, and asks for the lock then.
    item = await core_api.items.get_for_update_async(db, org_id, line.item_id)
    if item is not None:
        return item
    product = line.name or f'line {line.line_number}'
    raise CorrectionItemMissingError(product)


async def _locked_quantity(db: AsyncSession, doc: Document, item_id: UUID) -> Decimal:
    """The record's quantity once this transaction holds its row.

    Every executor writes an absolute quantity, worked out from what the
    record held. Reading that without the lock let two documents read the
    same number and both write it plus their own line, so one delivery
    vanished from the record while the ledger, raised by its movement, kept it —
    a drift of exactly one line. The lock is held to commit, so the number
    read here is still true when the write lands.
    """
    locked = await core_api.items.get_for_update_async(db, doc.organization_id, item_id)
    if locked is None:
        raise ServiceRejectionError('stock_record_not_found', item=item_id)
    return locked.quantity or Decimal('0')


async def _apply_qty_change(
    db: AsyncSession,
    doc: Document,
    item_id: UUID,
    new_qty: Decimal,
    user_id: UUID,
    history: dict[str, str],
) -> Any:
    """Call update_quantity with standard kwargs; raise if item vanishes.

    *new_qty* is absolute: derive it from ``_locked_quantity``, never from a
    record read without the lock.
    """
    updated = await core_api.items.update_quantity_async(
        db,
        doc.organization_id,
        item_id,
        new_qty,
        user_id=user_id,
        source_document_id=doc.id,
        history_changes=history,
        post_the_change=False,
    )
    if updated is None:
        raise ServiceRejectionError('stock_record_not_found', item=item_id)
    return updated


def _require_sufficient_stock(item: Any, qty: Decimal, item_id: UUID | None) -> None:
    """Raise ValueError if this one record holds less stock than requested.

    The record's own quantity is the whole truth only where there is no
    ledger to consult — stock with no product template, or an organization
    running no WMS module. Everywhere else ask ``_require_stock_at``.
    """
    available = item.quantity or Decimal('0')
    if available < qty:
        raise ServiceRejectionError(
            'stock_insufficient_record',
            item=item.name or item_id,
            available=item.quantity,
            requested=qty,
        )


async def _ledger_quantity_at(
    db: AsyncSession,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
) -> Decimal | None:
    """Physical stock of this product on this shelf, or None if unledgered.

    ``None`` means the records' view has nothing to say here — no live
    record of the product stands on that shelf — and the caller should fall
    back to the record's own quantity. It is not the same answer as
    ``Decimal(0)``, which means the view knows this shelf and finds it empty.

    The figure is physical quantity, not ``available``: a document that
    reached execution reserved its share at confirmation, and subtracting
    its own reservation would leave it refusing the goods it is holding.
    """
    quants = await core_api.stock.list_quants_async(
        db, org_id, template_id, location_id
    )
    if not quants:
        return None
    return sum((q.quantity for q in quants), Decimal('0'))


async def _require_stock_at(
    db: AsyncSession,
    doc: Document,
    *,
    item: Any,
    quantity: Decimal,
    template_id: UUID | None,
    location_id: UUID | None,
) -> None:
    """Refuse the line unless the shelf holds what it takes off it.

    Confirmation reserves against the group the records' view sums per
    (template, location); execution used to check ``Item.quantity``, which is
    one record's share of that same figure, split across however many
    records stand there. One product on one shelf in two records — two batches,
    or two deliveries that arrived apart — made the two numbers differ every
    time, so a document could pass confirmation and then break on its last
    step quoting a figure matching neither the shelf nor the reservation.
    """
    if template_id is not None and location_id is not None:
        on_hand = await _ledger_quantity_at(
            db, doc.organization_id, template_id, location_id
        )
        if on_hand is not None:
            if on_hand < quantity:
                raise ServiceRejectionError(
                    'stock_insufficient_record',
                    item=item.name if item else template_id,
                    available=on_hand,
                    requested=quantity,
                )
            return
    if item is not None:
        _require_sufficient_stock(item, quantity, item.id)


async def lock_document_stock_async(db: AsyncSession, doc: Document) -> None:
    """Lock the stock of every product the document names, before any of it moves.

    Completing a document walked its lines and each line locked what it took
    as it got there, so a dispatch of rice then flour and one of flour then
    rice each took one product and waited for the other's: the database
    aborted one of the two, and somebody got an error for a document nothing
    was wrong with. Confirming (which reserves line by line) and releasing
    a reservation did the same. Locked here, all at once and in the order
    every multi-group operation shares, the second document waits for the
    first.

    Every shelf of each product, not only the document's own: a dispatch
    drains the product's cost layers, which are kept per product whatever
    the shelf, so two documents of the same products from two different
    shelves met there instead. The groups the document's reservations hold
    come along, wherever they are. A line that names only a record is
    locked through the record's product; a record with no product yet has
    no stock in the register to lock.
    """
    templates: set[UUID] = {
        line.product_template_id
        for line in doc.lines
        if line.product_template_id is not None
    }
    for line in doc.lines:
        if line.product_template_id is None and line.item_id is not None:
            item = await core_api.items.get_async(db, doc.organization_id, line.item_id)
            if item is not None and item.template_id is not None:
                templates.add(item.template_id)
    keys: list[tuple[UUID, UUID | None]] = [
        (template_id, None) for template_id in templates
    ]
    # A receipt names the shelf its goods are meant for. Locked here with the
    # rest, each shelf is created and held in the one statement, instead of one
    # statement pair per line when the line gets there.
    from . import document_types as dt

    if dt.is_receipt(doc.type):
        for line in doc.lines:
            shelf = line.target_location_id or doc.target_location_id
            if line.product_template_id is not None and shelf is not None:
                keys.append((line.product_template_id, shelf))
    await core_api.stock.lock_async(
        db,
        doc.organization_id,
        keys=keys,
        reserved_for_document_id=doc.id,
    )


def _is_a_release_door(doc: Document) -> bool:
    """Whether this document deliberately carries held goods off a shelf.

    A hold stops goods from being *used*, not from being carried out or
    written off: a transfer is the release the guide names, and a scrap
    disposes of goods that will never be used. Ordinary dispatch, internal
    issue and picking are the doors the hold keeps shut.
    """
    from . import document_types as dt

    return dt.is_transfer(doc.type) or dt.is_scrap(doc.type)


async def _receipt_hold_document_ids_async(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
) -> list[UUID]:
    """The receipts whose batchless quarantine holds may still stand.

    A receipt reserves nothing at confirmation, so reservation rows owned by
    a completed receipt that held goods back are exactly the batchless
    quarantine holds (a named batch is held by its status instead). The
    profile's current quarantine location is not part of the identity: a
    later edit of that setting must not strand the goods already held.
    """
    stmt = (
        select(Document.id)
        .join(DocumentLine, DocumentLine.document_id == Document.id)
        .where(
            Document.organization_id == organization_id,
            Document.status == DocumentStatus.COMPLETED.value,
            DocumentLine.product_template_id == template_id,
            DocumentLine.held_quantity > Decimal('0'),
        )
        .distinct()
    )
    return list((await db.execute(stmt)).scalars().all())


async def _receipt_holds_at_async(
    db: AsyncSession,
    doc: Document,
    *,
    template_id: UUID,
    shelf_id: UUID | None,
) -> Decimal:
    """How much of this product on this shelf a receipt holds in quarantine."""
    if shelf_id is None:
        return Decimal('0')
    receipt_ids = await _receipt_hold_document_ids_async(
        db, doc.organization_id, template_id
    )
    if not receipt_ids:
        return Decimal('0')
    return await core_api.stock.held_quantity_async(
        db,
        doc.organization_id,
        template_id,
        shelf_id,
        document_ids=receipt_ids,
    )


async def _release_the_quarantine_hold_async(
    db: AsyncSession,
    doc: Document,
    *,
    template_id: UUID,
    shelf_id: UUID | None,
    quantity: Decimal,
    lot_id: UUID | None = None,
) -> None:
    """Drop the receipt's hold on goods a deliberate door is taking away.

    The batchless held quantity is reserved against the receipt that put it
    there, so every draw skips it. A transfer or a scrap carries the goods
    out by name; the part of the leaving quantity the free stock cannot
    cover is what the receipt's rows release, before the movement is
    written, or the movement would be refused as leaving a hold standing on
    goods that are no longer there.

    Only the receipt's rows are released. A confirmed dispatch that reserved
    the same shelf's free stock keeps its reservation; ``release_unbacked``
    is asked for the receipt documents alone.

    *lot_id* names the batch the door is confined to. A receipt hold is
    always on batchless goods, so a door taking a named batch releases
    nothing here.
    """
    if shelf_id is None or lot_id is not None:
        return
    if not _is_a_release_door(doc):
        return
    receipt_ids = await _receipt_hold_document_ids_async(
        db, doc.organization_id, template_id
    )
    if not receipt_ids:
        return
    await core_api.stock.release_unbacked_async(
        db,
        doc.organization_id,
        template_id,
        shelf_id,
        quantity,
        document_ids=receipt_ids,
    )


def _executed_quantity(line: DocumentLine) -> Decimal:
    return line.done_quantity


def line_source_shelf(
    line: DocumentLine, doc: Document, item: Any | None
) -> UUID | None:
    """The shelf a line takes from: its own pin, else the document's, else the record's.

    A dispatch from a zone pins each line to the shelf its share is drawn
    from at confirmation (``DocumentLine.source_location_id``); every other
    line has no pin and takes from the document's source, or, when the
    document names none, from the shelf its record stands on. The hold, the
    draw, the picking and the correction all answer by this one order, so a
    line cannot be held on one shelf and taken from another.
    """
    if line.source_location_id is not None:
        return line.source_location_id
    if doc.source_location_id is not None:
        return doc.source_location_id
    return item.location_id if item is not None else None


async def _adopt_card_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    item: Any,
    *,
    user_id: UUID,
    unit_confirmed_over_template: bool = False,
) -> UUID | None:
    """Give a record that predates its card the card its ledger writes need.

    The receipt adopts the card a legacy row lacks — the same resolve-or-
    mint the items service applies when a record opens — and the outbound
    doors need it for the same reason: their ledger writes were gated on
    ``stock_template_id``, the one id such a row does not have, so its
    quantity left the record while the movement register read empty. The
    record's own words resolve (or mint) the card, and the bind takes the
    unit gate every other door takes, so the conversion and every write
    below speak one unit. A mint inherits the record's unit — the record
    is what holds the stock — and, when the record names none, the line's:
    the only unit anyone gave this stock is the one this document used.

    A record kept in another unit than its card stops here unless the
    operator confirmed the difference on the execution screen
    (*unit_confirmed_over_template*, riding the completion payload). The
    refusal reaches that screen as a structured ``RECORD_UNIT_MISMATCH``
    naming the record and both units — the shape a client needs to ask the
    operator the question the bind used to have nobody to ask.

    Returns the adopted card's id, or None when *item* is None. Binding the
    card is all this helper does: the stock such a record holds never reached
    the ledger, and the door that adopts it must post it there itself — see
    :func:`_post_opening_balance_async` — before it moves any of it away.
    """
    if item is None:
        return None
    adopted = await core_api.product_templates.resolve_default_async(
        db,
        doc.organization_id,
        name=item.name,
        brand=item.brand,
        barcode=item.barcode,
        uom_id=item.uom_id or line.uom_id,
    )
    try:
        bound = await core_api.items.bind_template_async(
            db,
            doc.organization_id,
            item.id,
            adopted.id,
            user_id=user_id,
            source_document_id=doc.id,
            unit_confirmed_over_template=unit_confirmed_over_template,
        )
    except ServiceRejectionError as exc:
        if exc.key == 'item_unit_differs_from_template_confirmation_required':
            raise RecordUnitMismatchError(**exc.kwargs) from exc
        raise
    if bound is None:
        raise ServiceRejectionError('item_not_found')
    return adopted.id


async def _post_opening_balance_async(
    db: AsyncSession,
    doc: Document,
    *,
    item: Any,
    template_id: UUID | None,
    location_id: UUID | None,
    user_id: UUID,
    quantity: Decimal | None = None,
) -> None:
    """Put the stock a record already holds into the ledger it just joined.

    A record that predates its card keeps its stock nowhere but on itself —
    no movement, no cost layer — and adoption used to leave it there while
    the door went on moving it as if the register knew: the goods left the
    record, the shelf read empty, and from that moment the pair *(card,
    location)* said two different numbers about the same tray. The next
    dispatch of the same record came back refused by a shelf whose card was,
    at that moment, showing the remaining quantity, and the reconciliation
    report named a drift nobody had caused.

    Joining the ledger means saying what the record holds: a movement
    marked ``opening_balance`` at its own location, which the second pair of
    that report traces the shelf back to, and the cost layer its third pair
    measures the shelf against. What an opening writes is the Core's
    rule, the one its own edit and quantity paths take
    (``core_api.items.post_opening_balance_async``); this door used to keep
    a copy of it, and every change to the rule had to find both. What is
    left here is the door's own part: which shelf, and how much. The door's
    own movement is what says the goods left; the opening only says what
    stood there before it.

    The record's location comes first: it is the shelf the records' view
    counts the stock under, so the opening has to stand there for the shelf
    and its ledger to agree. A record that names no location has its stock
    posted where the door is taking it from, and one that holds nothing
    posts nothing.

    That order is the reverse of the door's own taking, which reads
    ``line_source_shelf`` — a dispatch takes from where the line says, the
    shelf its zone pinned or else the document's source, not from where the
    record stands. The two resolve differently only when the record stands
    off that shelf, and confirmation refuses a record off the source of a
    line that asks for stock (``_refuse_record_off_its_shelf``), so the
    disagreement never gets this far.

    *quantity* states the holding outright where the record has already been
    topped up by the time the card is adopted (the receipt changes the
    record before it reads the card): left out, the helper reads the
    record's current holding, which there would include the delivery and
    post it twice.
    """
    if location_id is None:
        return
    if template_id is None:
        return
    holding = (
        quantity if quantity is not None else await _locked_quantity(db, doc, item.id)
    )
    await core_api.items.post_opening_balance_async(
        db,
        doc.organization_id,
        item.id,
        template_id=template_id,
        holding=holding,
        user_id=user_id,
        location_id=location_id,
    )


async def _resolve_lot(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    *,
    create_if_missing: bool = True,
) -> UUID | None:
    lot_name = line.serial_number or line.batch_number
    if not lot_name or not line.product_template_id:
        return None
    if not create_if_missing:
        # For outbound docs, look up existing lot but do not create phantom lots
        existing = await core_api.stock.list_lots_async(
            db,
            organization_id=doc.organization_id,
            product_template_id=line.product_template_id,
        )
        for lot in existing:
            if lot.name == lot_name:
                return lot.id
        return None
    return await core_api.stock.get_or_create_lot_async(
        db,
        organization_id=doc.organization_id,
        product_template_id=line.product_template_id,
        name=lot_name,
        is_serial=bool(line.serial_number),
        expiry_date=line.expiry_date,
    )
