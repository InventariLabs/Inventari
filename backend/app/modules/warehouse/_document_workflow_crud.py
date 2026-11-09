from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.i18n.service import stated_quantity

from . import document_types as dt
from ._document_workflow_helpers import (  # noqa: F401
    _apply_execution_quantities,
    _apply_line_tax_rates,
    _build_partner_snapshot,
    _check_document_period_open,
    _freeze_print_details,
)
from ._order_side import order_side_async
from ._stock_executor_helpers import (
    _is_a_release_door,
    _receipt_holds_at_async,
    _resolve_lot,
    line_source_shelf,
    lock_document_stock_async,
)
from .document_line_resolver import build_document_line
from .document_line_split import insert_sibling_lines_async
from .document_numbering_service import (
    is_temporary_number,
    number_for_date_async,
    temporary_number,
)
from .document_profile_service import get_or_create_profile, resolve_document_currency
from .document_return_service import (
    keep_return_within_left_async,
    keep_the_copy_a_return_async,
    relink_return_lines,
    return_links,
)
from .document_validation_service import (
    validate_lines_async,
    validate_lines_data_async,
    validate_location_async,
    validate_locations_async,
    validate_partner_async,
    validate_unit_prices_async,
)
from .document_value_service import compute_line_values, recompute_document_values
from .inventory_period_service import check_period_not_closed_async
from .models import FREE_TEXT_REASON_CODE, Document, DocumentLine, DocumentStatus
from .pre_post_checks import notify_withdrawn_async
from .schemas import DocumentCreate, DocumentUpdate
from .stock_reservation_service import (
    release_for_document_async,
    reserve_for_document_async,
)

logger = get_logger(__name__)


async def get_or_raise(db: AsyncSession, org_id: UUID, doc_id: UUID) -> Document:
    # Direct import — the local import of document_workflow_service
    # masked a real import cycle (workflow_service -> _document_workflow_crud
    # -> workflow_service). get_document lives in document_query_service.
    from .document_query_service import get_document

    doc = await get_document(db, org_id, doc_id)
    if not doc:
        raise ServiceRejectionError('document_not_found')
    return doc


async def _get_doc_for_update(db: AsyncSession, org_id: UUID, doc_id: UUID) -> Document:
    """Take the document's row before reading it, for the whole transaction.

    Every status transition goes through this door, in the same order —
    the row first, the stock after — so two doors meeting on one document
    serialize here, and each decides on the status the other left behind
    rather than on one that is already gone.
    """
    from .models import Document as DocModel

    result = await db.execute(
        select(DocModel)
        .where(DocModel.id == doc_id, DocModel.organization_id == org_id)
        .with_for_update()
    )
    doc = result.scalars().first()
    if not doc:
        raise ServiceRejectionError('document_not_found')
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def _record_stands_elsewhere(
    db: AsyncSession,
    doc: Document,
    item: Any,
    message_key: str = 'document_record_stands_elsewhere',
    **extra: Any,
) -> ServiceRejectionError:
    """The refusal for a record standing on another shelf than the document's.

    It names the record and both shelves, and says what to change. A bare
    disagreement uses the one wording every door shares; a shortfall adds
    its numbers through ``message_key`` and ``extra``.
    """
    record_shelf_id = item.location_id
    document_shelf_id = doc.source_location_id
    record_shelf = await core_api.locations.get_async(
        db, doc.organization_id, record_shelf_id
    )
    document_shelf = (
        await core_api.locations.get_async(db, doc.organization_id, document_shelf_id)
        if document_shelf_id is not None
        else None
    )
    return ServiceRejectionError(
        message_key,
        item_name=item.name,
        record_shelf=record_shelf.name if record_shelf else str(record_shelf_id),
        document_shelf=(
            document_shelf.name if document_shelf else str(document_shelf_id)
        ),
        **extra,
    )


def _stands_off_the_source(doc: Document, item: Any) -> bool:
    """True when both shelves are named and they are not the same one."""
    return (
        item.location_id is not None
        and doc.source_location_id is not None
        and item.location_id != doc.source_location_id
    )


async def _refuse_record_off_its_shelf(
    db: AsyncSession, doc: Document, line: DocumentLine, item: Any
) -> None:
    """Refuse confirmation when a cardless record stands off the source.

    A line that names no card reserves nothing — and a record that predates
    its card is exactly such a line, so confirmation passed it unheard. The
    door that adopts the card at completion then takes the goods from the
    document's source while the opening balance posts them where the record
    stands, and with the two shelves named and different that document could
    only die mid-flight: confirmed, refused at completion, stuck. The refusal
    belongs here, while the document is still a draft the reader can fix —
    point it at the shelf the record stands on, or move the record.

    A carded record needs no such gate: its line reserves against the card
    at the source, and the reservation itself refuses a short shelf. A line
    that asks for nothing takes nothing, so it is nobody's disagreement.
    """
    if item is None or item.template_id is not None:
        return
    if (line.expected_quantity or Decimal(0)) - (line.done_quantity or Decimal(0)) <= 0:
        return
    if _stands_off_the_source(doc, item):
        raise await _record_stands_elsewhere(db, doc, item)


async def _shelves_below_the_source(
    db: AsyncSession, doc: Document
) -> list[UUID] | None:
    """The shelves under the document's source when that source is a zone.

    A dispatch or a transfer may name a zone, a location with locations
    under it, as its source. Its lines then take from the shelves below —
    each line on the shelf its share is drawn from. Any other source is an
    exact shelf and answers None, as does a location with nothing under it.
    """
    if doc.source_location_id is None or not (
        dt.is_dispatch(doc.type) or dt.is_transfer(doc.type)
    ):
        return None
    below = await core_api.locations.descendant_ids_async(
        db, doc.organization_id, doc.source_location_id
    )
    return below or None


def _stands_off_the_shelf(item: Any, shelf: UUID | None) -> bool:
    """True when the record stands on a shelf other than the one the line takes from."""
    return (
        item.location_id is not None and shelf is not None and item.location_id != shelf
    )


async def _reserve_quants_for_doc(db: AsyncSession, doc: Document) -> None:
    """Block the stock the document still expects to take.

    The hold looks where the draw will: the card is the line's, else the
    record's, and the shelf is the line's own shelf, else the document's
    source, else the shelf the record stands on — a write-off names no
    source, and holding by the product alone blocked the oldest stock
    anywhere while the record the line pointed at was the one that left.
    A line naming a record but no card holds the record's card stock all
    the same.

    When the document's source is a zone, a dispatch line is first split over
    the shelves below it (``_hold_a_zone_line``), and a transfer line is
    pinned to the shelf its record stands on; either way each line then holds
    on the shelf it is pinned to.

    The line may be written in the supplier's unit; the stock it reserves
    against is kept in the product's, and execution converts before it takes
    anything. Reserving the line's own number put the two steps on different
    scales: half a kilo asked for in grams read as five hundred kilos, so
    confirmation refused a dispatch the shelf could cover — or, the other way
    round, a kilo written as one blocked a thousandth of what would leave.

    A transfer or a scrap off a shelf that holds a receipt's quarantine
    quantity may count that quantity as already held: it is the goods the
    door releases, so reserving it again would find nothing free and refuse
    the release. Only the part beyond the receipt's hold is reserved, which
    keeps ordinary stock protected exactly as any other document's is. The
    relief is per product and shelf, so two lines of one document cannot
    both lean on the same held quantity; a line naming a batch gets none of
    it, because a receipt's hold is on batchless goods.
    """
    await lock_document_stock_async(db, doc)
    below = await _shelves_below_the_source(db, doc)
    receipt_hold_left: dict[tuple[UUID, UUID], Decimal] = {}
    for line in list(doc.lines):
        item = (
            await core_api.items.get_async(db, doc.organization_id, line.item_id)
            if line.item_id
            else None
        )
        template_id = line.product_template_id or (
            item.template_id if item is not None else None
        )
        if template_id is None:
            await _refuse_record_off_its_shelf(db, doc, line, item)
            continue
        needed = await core_api.uoms.to_stock_uom_async(
            db,
            doc.organization_id,
            template_id,
            line.expected_quantity - line.done_quantity,
            line.uom_id,
        )
        if needed <= 0:
            continue
        if below is not None and line.source_location_id is None:
            if dt.is_transfer(doc.type):
                await _pin_a_transfer_line(db, doc, line, item, below)
            else:
                await _hold_a_zone_line(db, doc, line, item, template_id, needed, below)
                continue
        await _hold_line_on_shelf(
            db,
            doc,
            line,
            item,
            template_id=template_id,
            needed=needed,
            receipt_hold_left=receipt_hold_left,
        )


async def _hold_line_on_shelf(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    item: Any,
    *,
    template_id: UUID,
    needed: Decimal,
    receipt_hold_left: dict[tuple[UUID, UUID], Decimal],
) -> None:
    """Reserve *needed* (stock unit) for a line on the shelf the line takes from."""
    shelf = line_source_shelf(line, doc, item)
    covered = Decimal('0')
    if (
        shelf is not None
        and _is_a_release_door(doc)
        and item is not None
        and item.lot_id is None
        and not line.batch_number
        and not line.serial_number
    ):
        key = (template_id, shelf)
        left = receipt_hold_left.get(key)
        if left is None:
            left = await _receipt_holds_at_async(
                db, doc, template_id=template_id, shelf_id=shelf
            )
        covered = min(left, needed)
        receipt_hold_left[key] = left - covered
    to_reserve = needed - covered
    if to_reserve <= 0:
        return
    lot_id = await _the_batch_the_door_takes(db, doc, line, item)
    result = await reserve_for_document_async(
        db,
        organization_id=doc.organization_id,
        product_template_id=template_id,
        location_id=shelf,
        needed_qty=to_reserve,
        document_id=doc.id,
        document_line_id=line.id,
        lot_id=lot_id,
        require_active_lot=lot_id is None,
    )
    if not result.success:
        # The numbers enter a translated sentence a person reads beside
        # the screen's own quantities, so they are stated the way the
        # screen states them — the store's scale (`2.000`) is not a
        # number anybody typed.
        if item is not None and _stands_off_the_shelf(item, shelf):
            raise await _record_stands_elsewhere(
                db,
                doc,
                item,
                'document_insufficient_stock_record_elsewhere',
                quantity=stated_quantity(result.unreserved_quantity),
                needed=stated_quantity(needed),
            )
        raise ServiceRejectionError(
            'document_insufficient_stock',
            quantity=stated_quantity(result.unreserved_quantity),
            needed=stated_quantity(needed),
        )


async def _the_batch_the_door_takes(
    db: AsyncSession, doc: Document, line: DocumentLine, item: Any
) -> UUID | None:
    """The batch a write-off or a transfer line will take by name, held or not.

    A quarantined batch is never dispatchable, so a hold planned over
    dispatchable stock found nothing and refused the document: writing off
    goods held back at the receipt meant releasing the batch for picking
    first, open to any dispatch in between. The scrap and the transfer take
    the batch they name whatever its state (``_take_the_line_off_the_records``,
    ``_carry_the_records_stock``), so the hold names the same batch on the
    same terms: the line's batch, and for a transfer, which carries its
    record as itself, the record's own. Any other door, and a line naming
    none, answers None and holds by the removal strategy as before.
    """
    if not _is_a_release_door(doc):
        return None
    lot_id = await _resolve_lot(db, doc, line, create_if_missing=False)
    if lot_id is None and dt.is_transfer(doc.type) and item is not None:
        records_batch: UUID | None = item.lot_id
        return records_batch
    return lot_id


async def _pin_a_transfer_line(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    item: Any,
    below: list[UUID],
) -> None:
    """Pin a transfer line from a zone to the shelf its record stands on.

    A transfer moves exactly the record its line names, so it needs no split:
    the record must stand under the zone, and the line takes from its shelf.
    """
    if item is None:
        return
    if item.location_id not in {doc.source_location_id, *below}:
        raise await _record_stands_elsewhere(db, doc, item)
    line.source_location_id = item.location_id


async def _hold_a_zone_line(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    item: Any,
    template_id: UUID,
    needed: Decimal,
    below: list[UUID],
) -> None:
    """Split a dispatch line over the shelves under its zone, and hold each share.

    The plan takes the records of the product on every shelf of the zone in
    the product's removal order, as one list. Each shelf it reaches becomes a
    share of the line: the line itself keeps the first, each other share is a
    sibling line, pinned to its shelf, whose item is the first record the
    plan drew there. Then every share is held on its shelf like any line that
    names one. A record the line names that stands outside the zone is refused
    as before. A line that names a batch is planned over that batch alone, and
    every share keeps it.

    The plan is read in the stock unit. A line written in another unit can
    still take from one shelf, but splitting it would mean converting each
    share back, which rounds; such a line is refused instead.
    """
    zone = doc.source_location_id
    assert zone is not None, 'a zone split names the zone it splits'
    subtree = [zone, *below]
    if item is not None and item.location_id not in subtree:
        raise await _record_stands_elsewhere(db, doc, item)
    draws = await core_api.stock.plan_draw_async(
        db,
        doc.organization_id,
        template_id,
        None,
        needed,
        any_owner=True,
        by_record=True,
        lot_id=await _resolve_lot(db, doc, line, create_if_missing=False),
        among_shelves=subtree,
    )
    taken = sum((draw.consumed for draw in draws), Decimal('0'))
    if taken < needed:
        raise ServiceRejectionError(
            'document_insufficient_stock',
            quantity=stated_quantity(taken),
            needed=stated_quantity(needed),
        )
    shares: dict[UUID, tuple[UUID, Decimal]] = {}
    for draw in draws:
        shelf, record_id = draw.location_id, draw.record_id
        assert shelf is not None and record_id is not None  # a plan by record
        first_record, quantity = shares.get(shelf, (record_id, Decimal('0')))
        shares[shelf] = (first_record, quantity + draw.consumed)
    in_stock_unit = needed == line.expected_quantity - line.done_quantity
    if len(shares) > 1 and not in_stock_unit:
        raise ServiceRejectionError(
            'document_zone_split_needs_stock_unit',
            item_name=item.name if item is not None else str(template_id),
        )

    (first_shelf, (first_record, first_quantity)), *rest = shares.items()
    taken_elsewhere = sum((q for _, (_, q) in rest), Decimal('0'))
    line.source_location_id = first_shelf
    line.item_id = first_record
    line.quantity -= taken_elsewhere
    line.expected_quantity -= taken_elsewhere
    compute_line_values(line)
    clones = await insert_sibling_lines_async(
        db,
        doc,
        line,
        [
            {
                'source_location_id': shelf,
                'item_id': record_id,
                'quantity': quantity,
                'expected_quantity': quantity,
                'done_quantity': Decimal('0'),
                'batch_number': line.batch_number,
            }
            for shelf, (record_id, quantity) in rest
        ],
    )
    holds = [(line, first_record, first_quantity)]
    holds += [
        (clone, record_id, quantity)
        for clone, (_, (record_id, quantity)) in zip(clones, rest, strict=True)
    ]
    for hold_line, record_id, quantity in holds:
        record = await core_api.items.get_async(db, doc.organization_id, record_id)
        await _hold_line_on_shelf(
            db,
            doc,
            hold_line,
            record,
            template_id=template_id,
            needed=quantity,
            receipt_hold_left={},
        )


def _unpin_the_lines(doc: Document) -> None:
    """Forget the shelves the lines were pinned to, once their holds are let go.

    A line pinned by a dispatch from a zone keeps its shelf only while the
    hold on it stands; a document that goes back to a draft or is cancelled
    gives the holds back, so the next confirmation plans the zone again. The
    split lines themselves stay.
    """
    for line in doc.lines:
        line.source_location_id = None


async def _release_quants_for_doc(db: AsyncSession, doc: Document) -> None:
    # Completion releases first and executes after: locked here, the
    # document holds its stock before the first reservation row changes.
    await lock_document_stock_async(db, doc)
    await release_for_document_async(
        db,
        organization_id=doc.organization_id,
        document_id=doc.id,
    )


async def _currency_from_named_order_lines_async(
    db: AsyncSession, org_id: UUID, lines: list[Any]
) -> str | None:
    """The single currency the order lines a document names are written in.

    A receipt that loads an order's lines copies the order's unit prices
    digit for digit. Stamping it with the organization's currency would
    print those numbers under another sign, unconverted — the same defect
    the receipt-from-order path already answers by carrying the order's
    currency. That path passes it explicitly; a one-screen post has no
    caller to ask, so the answer comes from the order lines the payload
    already names. Mixed or absent currencies leave the organization's
    answer in place, which is what every other document gets.
    """
    po_line_ids = [line.source_po_line_id for line in lines if line.source_po_line_id]
    if not po_line_ids:
        return None
    orders = await order_side_async(db, org_id)
    if orders is None:
        return None
    currencies = await orders.get_currencies_for_lines_async(db, org_id, po_line_ids)
    distinct = {currency for currency in currencies.values() if currency}
    return distinct.pop() if len(distinct) == 1 else None


async def document_of_press(
    db: AsyncSession, org_id: UUID, post_key: str
) -> Document | None:
    """The document a press already made, or ``None`` for a press not seen yet.

    ``post_key`` names one press of a screen. The same press sent again — a
    double click, a retry after the answer was lost on the way back — must be
    answered with what the first one wrote, not write a second document. The
    lock makes the second wait for the first to commit instead of racing it,
    and holds until this transaction ends, so the caller writes the key on the
    document it makes before anyone else can look.
    """
    await acquire_advisory_lock(db, f'document_post_key:{org_id}:{post_key}')
    return (
        await db.execute(
            select(Document)
            .where(Document.organization_id == org_id, Document.post_key == post_key)
            .options(selectinload(Document.lines))
        )
    ).scalar_one_or_none()


async def create_document(
    db: AsyncSession,
    org_id: UUID,
    data: DocumentCreate,
    user_id: UUID,
    *,
    currency: str | None = None,
    stock_already_applied: bool = False,
    post_key: str | None = None,
) -> Document:
    """Create a DRAFT document.

    ``post_key`` names the press, as on ``post_new_document``: a draft saved
    again under the key of a save whose answer was lost is answered with the
    draft the first save wrote, so the reader does not find two in Drafts.

    ``currency`` is for callers that build a document out of one already
    priced elsewhere — a receipt made from a purchase order, say. Passing it
    stops the header being stamped with the organization's currency while the
    lines carry the source's amounts unconverted. It is a keyword, not a
    request field: the currency of a document nobody derived it from is the
    organization's, and a client does not get to say otherwise.

    ``stock_already_applied`` is the same kind of keyword: it marks a document
    that only records a movement another module already made, so confirming and
    completing it leave the shelves alone.
    """
    from . import document_types as dt
    from .document_type_config_service import get_type_config

    if post_key:
        made = await document_of_press(db, org_id, post_key)
        if made is not None:
            return made

    # The closure dialog says documents dated in the month "can no longer be
    # created or edited", and until now only the second half was true: the
    # guard read the date off a document, so it could not run before one
    # existed. A document born into a closed month is unusable — it cannot be
    # confirmed, completed, updated or cancelled — so it is refused at the
    # door, where the message can still be acted on by changing the date.
    await check_period_not_closed_async(
        db, org_id, data.scheduled_date or datetime.now(UTC).date()
    )

    # the organization's per-type configuration finally applies. It
    # fills the locations the operator would pick every time anyway, and it can
    # demand a partner on a type the Core rules leave optional.
    type_config = await get_type_config(db, org_id, dt.normalize(data.type))
    if type_config:
        data.source_location_id = (
            data.source_location_id or type_config.default_source_location_id
        )
        data.target_location_id = (
            data.target_location_id or type_config.default_target_location_id
        )

    # IN (Receipt) and OUT (Delivery) require a partner (supplier/customer) —
    # but only when the partners module is enabled. With the module off the
    # UI hides the partner field, so blocking here would deadlock the flow
    # . Mirrors the modules fallback: empty enabled_modules = all on.
    partner_required = dt.requires_partner(data.type) or bool(
        type_config and type_config.require_partner
    )
    if partner_required and not data.partner_id:
        org = await core_api.organizations.get_async(db, org_id)
        enabled = set(org.enabled_modules or []) if org else set()
        if not enabled or 'partners' in enabled:
            raise ServiceRejectionError('document_type_requires_partner')

    await validate_locations_async(
        db,
        org_id,
        data.type,
        data.source_location_id,
        data.target_location_id,
    )
    partner = None
    if data.partner_id:
        # Kept, not discarded: the journal entry below names the partner, and
        # the row has just been read to validate it.
        partner = await validate_partner_async(db, org_id, data.partner_id, data.type)
    if data.reason_code is not None and not dt.is_scrap(data.type):
        raise ServiceRejectionError('document_reason_scrap_only')
    if dt.is_scrap(data.type):
        _require_scrap_reason(data.reason_code, data.notes)
    await validate_lines_async(db, org_id, data)
    await validate_unit_prices_async(db, org_id, data.lines, data.type)

    # Before the document, not after: the profile defaults the header is
    # read from — the currency, the tax rule — belong to a profile that
    # exists before the first document of an organization is written, or
    # that first document answers differently from every one after it.
    profile = await get_or_create_profile(db, org_id)
    currency = (
        currency
        or await _currency_from_named_order_lines_async(db, org_id, data.lines)
        or await resolve_document_currency(db, org_id, profile)
    )
    doc = Document(
        organization_id=org_id,
        type=data.type,
        status=DocumentStatus.DRAFT.value,
        partner_id=data.partner_id,
        source_location_id=data.source_location_id,
        target_location_id=data.target_location_id,
        scheduled_date=data.scheduled_date,
        notes=data.notes,
        external_reference=data.external_reference,
        meta_data=data.meta_data or None,
        reason_code=data.reason_code.value if data.reason_code else None,
        created_by=user_id,
        currency=currency,
        stock_already_applied=stock_already_applied,
        post_key=post_key,
    )
    for i, line_data in enumerate(data.lines, 1):
        doc.lines.append(
            await build_document_line(
                line_data, i, currency=currency, db=db, org_id=org_id
            )
        )
    await _apply_line_tax_rates(db, org_id, profile, doc.lines)
    # A draft is a plan, so it carries an identifier of its own rather than
    # a number of the register: numbers are given out when a draft is
    # confirmed (see confirm_document), where the counter row is claimed as
    # the last step before that write. Nothing here touches the counter, so
    # a plan written and thrown away costs the register nothing.
    doc.number = temporary_number()
    db.add(doc)
    await db.flush()
    recompute_document_values(doc)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'type': doc.type,
            'partner_id': str(doc.partner_id) if doc.partner_id else None,
            # Who the goods come from, in the word the register prints: an id
            # is not an answer to that question months later.
            'partner_name': partner.name if partner else None,
        },
    )
    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def duplicate_document(
    db: AsyncSession,
    org_id: UUID,
    source_doc_id: UUID,
    user_id: UUID,
) -> Document:
    """Create a new DRAFT document as a copy of ``source_doc_id``.

    Copies type, partner, locations, scheduled_date, notes,
    external_reference, the reason a scrap or a return was written with, the
    fields modules keep in ``meta_data`` and all lines (expected_quantity,
    template, name/brand/barcode, uom, batch, serial, expiry, unit_price,
    tax_rate, ``meta_data``). A copy of a return is a return of the same
    document, and is refused when that has too little left to give back.
    A correction is not copied: it restates one document, and a second
    correction of it is written from that document.
    The new document always starts in DRAFT with an identifier of its own
    — even if the source is COMPLETED or CANCELLED — so it can be edited
    before confirmation, which is where its number is drawn. Done
    quantities are NOT copied.
    """
    source = await get_or_raise(db, org_id, source_doc_id)
    await db.refresh(source, attribute_names=['lines'])

    from . import document_types as dt
    from .schemas import DocumentCreate, DocumentLineCreate

    if dt.is_correction(source.type):
        raise ServiceRejectionError('document_correction_not_duplicable')

    # A receipt copies the product only: the record it lands on is decided
    # when the goods arrive. A document that takes goods off a shelf names the
    # record it takes, and confirming refuses a line that names none — so a
    # copy without it could not be confirmed until every line was picked
    # again. A receipt line that names no product keeps its record for the
    # same reason: the record is all it says of its goods, and confirming
    # refuses a receipt line that names neither. The record is kept while it
    # is still there; one deleted since is left out, and confirming names the
    # line that needs a new one.
    named_records = {
        line.item_id
        for line in source.lines
        if line.item_id
        and (dt.requires_stock_row(source.type) or not line.product_template_id)
    }
    live_records = (
        await core_api.items.existing_ids_async(db, org_id, named_records)
        if named_records
        else set()
    )
    line_copies = [
        DocumentLineCreate(
            item_id=line.item_id if line.item_id in live_records else None,
            product_template_id=line.product_template_id,
            name=line.name,
            brand=line.brand,
            barcode=line.barcode,
            sku=line.sku,
            expected_quantity=line.expected_quantity,
            uom_id=line.uom_id,
            batch_number=line.batch_number,
            serial_number=line.serial_number,
            expiry_date=line.expiry_date,
            notes=line.notes,
            unit_price=line.unit_price,
            tax_rate=line.tax_rate,
            meta_data=line.meta_data,
        )
        for line in source.lines
    ]
    data = DocumentCreate(
        type=source.type,
        partner_id=source.partner_id,
        source_location_id=source.source_location_id,
        target_location_id=source.target_location_id,
        scheduled_date=source.scheduled_date,
        notes=source.notes,
        external_reference=source.external_reference,
        lines=line_copies,
        # Only a scrap takes its reason through the create schema; a return's
        # reason is a code of its own, copied below.
        reason_code=source.reason_code if dt.is_scrap(source.type) else None,
        meta_data=source.meta_data,
    )
    copy = await create_document(db, org_id, data, user_id)
    if source.reason_code and not dt.is_scrap(source.type):
        copy.reason_code = source.reason_code
        await db.flush()
    await keep_the_copy_a_return_async(db, org_id, copy, source)
    return copy


def _require_scrap_reason(reason_code: str | None, notes: str | None) -> None:
    """Refuse a scrap that does not say why the goods are written off.

    The form asks for it, and so do the create schemas of corrections and
    returns; a scrap posted by a script, a phone flow or another module is
    asked the same, or the month-end grouping by reason gets a row it cannot
    place. OTHER names no reason of its own, so there the note is the reason.
    """
    if reason_code is None or (
        reason_code == FREE_TEXT_REASON_CODE and not (notes or '').strip()
    ):
        raise ServiceRejectionError('document_scrap_reason_required')


def _write_scrap_reason(doc: Document, data: DocumentUpdate, sent: set[str]) -> None:
    """Write the reason a scrap draft was sent with; any other type refuses it.

    A scrap is asked what it will hold once the payload is in, so clearing
    the reason, or the note an OTHER stands on, is refused the way creating
    the scrap without them is.
    """
    from . import document_types as dt

    if dt.is_scrap(doc.type):
        _require_scrap_reason(
            data.reason_code if 'reason_code' in sent else doc.reason_code,
            data.notes if 'notes' in sent else doc.notes,
        )
    if 'reason_code' not in sent:
        return
    if not dt.is_scrap(doc.type):
        raise ServiceRejectionError('document_reason_scrap_only')
    doc.reason_code = data.reason_code.value if data.reason_code else None


async def _apply_header_fields_async(
    db: AsyncSession,
    org_id: UUID,
    doc: Document,
    data: DocumentUpdate,
    sent: set[str],
) -> None:
    """Write the header fields the payload carried, and only those.

    Read where the payload's key set is still visible (AGENTS.md §2b): a
    named null clears, an absent key leaves the column alone, and a column
    this document may not leave empty is refused by name before anything is
    written.
    """
    from . import document_types as dt
    from .document_type_config_service import get_type_config

    _write_scrap_reason(doc, data, sent)
    if 'partner_id' in sent:
        if data.partner_id is None:
            if await _partner_required_async(db, org_id, doc.type):
                _refuse_cleared(['partner_id'])
            doc.partner_id = None
        else:
            await validate_partner_async(db, org_id, data.partner_id, doc.type)
            doc.partner_id = data.partner_id
    if 'source_location_id' in sent:
        if data.source_location_id is None:
            if dt.requires_source(doc.type):
                _refuse_cleared(['source_location_id'])
            doc.source_location_id = None
        else:
            await validate_location_async(db, org_id, data.source_location_id)
            doc.source_location_id = data.source_location_id
    if 'target_location_id' in sent:
        if data.target_location_id is None:
            if dt.requires_target(doc.type):
                _refuse_cleared(['target_location_id'])
            doc.target_location_id = None
        else:
            await validate_location_async(db, org_id, data.target_location_id)
            doc.target_location_id = data.target_location_id
    if 'scheduled_date' in sent and data.scheduled_date != doc.scheduled_date:
        # Clearing is a date change like any other. A document already
        # carrying a number is filed under the period it was numbered in,
        # so moving it re-files its number there — one document, one
        # period, which is what the date-based prefix exists to remove.
        # A draft still waiting for its number has nothing to move: its
        # date travels to confirmation, where the number is drawn from it.
        doc.scheduled_date = data.scheduled_date
        if not is_temporary_number(doc.number):
            from . import document_types as dt
            from .document_type_config_service import get_type_config

            type_config = await get_type_config(db, org_id, dt.normalize(doc.type))
            doc.number = await number_for_date_async(
                db,
                org_id,
                doc.type,
                doc.number,
                type_config.sequence_format if type_config else None,
                doc.scheduled_date,
            )
    if 'notes' in sent:
        doc.notes = data.notes
    if 'external_reference' in sent:
        doc.external_reference = data.external_reference
    if 'meta_data' in sent:
        doc.meta_data = data.meta_data or None


def _refuse_cleared(fields: list[str]) -> NoReturn:
    """Refuse a named null on a column this document may not leave empty.

    The same sentence, and the same exception, the putaway rule's refusal
    speaks (AGENTS.md §2b: modules share the message and the refusal set, not
    the helper) — a structured 400 naming the field, so the reader meets one
    shape wherever a field cannot be cleared.
    """
    raise ServiceRejectionError(
        'field_cannot_be_cleared', fields=', '.join(sorted(fields))
    )


async def _partner_required_async(
    db: AsyncSession, org_id: UUID, doc_type: str
) -> bool:
    """Whether this document may not stand without a partner — the same
    question create asks, so a null reaching update answers it the same way."""
    from . import document_types as dt
    from .document_type_config_service import get_type_config

    type_config = await get_type_config(db, org_id, dt.normalize(doc_type))
    if not (
        dt.requires_partner(doc_type) or (type_config and type_config.require_partner)
    ):
        return False
    org = await core_api.organizations.get_async(db, org_id)
    enabled = set(org.enabled_modules or []) if org else set()
    # With the partners module off the UI hides the field, so blocking here
    # would deadlock the flow. Empty enabled_modules = all on.
    return not enabled or 'partners' in enabled


# The pair this writer's journal keys come from: `update_document` logs the
# `fields` list cut from the update payload, so every key it can write is a
# field the schema and the model share. The snapshot-key exporter reads this
# declaration (backend/scripts/export_audit_snapshot_keys.py).
AUDIT_PAYLOAD_SCHEMA = ('DocumentUpdate', 'Document')


async def update_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    data: DocumentUpdate,
    user_id: UUID,
) -> Document:
    doc = await get_or_raise(db, org_id, doc_id)
    await _check_document_period_open(db, org_id, doc)
    if doc.status != DocumentStatus.DRAFT.value:
        raise ServiceRejectionError('document_update_status')

    # Presence decides, not truthiness (AGENTS.md §2b): a key the payload
    # carried is the client's instruction — a null clearing the column — and
    # a key it did not carry leaves the column alone. The blanket
    # ``is not None`` this replaces erased every clearing instruction, which
    # is why a cleared note or partner answered "updated" and changed
    # nothing.
    sent = data.model_fields_set

    if doc.type == 'CORRECTION':
        if 'notes' in sent:
            doc.notes = data.notes
        # Another module's fields are not the correction's business content,
        # so a module may still require one here.
        if 'meta_data' in sent:
            doc.meta_data = data.meta_data or None
        # Everything else is locked on a correction, and carrying the key is
        # the attempt: a null here is a clearing instruction on a column that
        # may not be cleared, so it is refused rather than dropped.
        set_forbidden = [
            k
            for k in (
                'partner_id',
                'source_location_id',
                'target_location_id',
                'scheduled_date',
                'external_reference',
                'lines',
            )
            if k in sent
        ]
        if set_forbidden:
            raise ServiceRejectionError(
                'document_correction_locked', fields=', '.join(set_forbidden)
            )
        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.DOCUMENT,
            target_id=doc.id,
            snapshot={
                'number': doc.number,
                'type': doc.type,
                'fields': sorted(sent & {'notes', 'meta_data'}),
            },
        )
        await db.flush()
        await db.refresh(doc, attribute_names=['lines'])
        return doc

    await _apply_header_fields_async(db, org_id, doc, data, sent)

    if 'lines' in sent:
        if data.lines is None:
            _refuse_cleared(['lines'])
        await validate_lines_data_async(db, org_id, data.lines, doc.type)
        await validate_unit_prices_async(db, org_id, data.lines, doc.type)
        # A return's lines give back lines of its original, and the form
        # does not send that link: read it before the lines are rewritten.
        links = return_links(doc.lines) if getattr(doc, 'return_of_id', None) else []
        doc.lines.clear()
        await db.flush()
        profile = await get_or_create_profile(db, org_id)
        currency = await resolve_document_currency(db, org_id, profile)
        # keep the header in step with the lines — the profile's
        # currency override may have changed since the document was created.
        doc.currency = currency
        for i, line_data in enumerate(data.lines, 1):
            doc.lines.append(
                await build_document_line(
                    line_data,
                    i,
                    document_id=doc.id,
                    currency=currency,
                    db=db,
                    org_id=org_id,
                )
            )
        await _apply_line_tax_rates(db, org_id, profile, doc.lines)
        if links:
            relink_return_lines(links, doc.lines)
            await db.flush()
            await keep_return_within_left_async(db, org_id, doc)

    recompute_document_values(doc)
    # The header and the lines are the record's business content: what the
    # editor changed is the entry's whole point, so the sent keys travel.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'type': doc.type,
            'fields': sorted(sent),
        },
    )
    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def _received_in_open_session_async(
    db: AsyncSession, org_id: UUID, line_id: UUID
) -> bool:
    """Whether a receiving session still open has already received this line.

    The line's shelf is where its goods were put: re-aiming it from the
    document page, behind the open receiving dialog, re-planned a line the
    session had just closed, and the stock was later booked onto the new
    shelf while the goods stood on the old one.
    """
    from .models import WmsPickLine, WmsPickSession

    received = await db.scalar(
        select(WmsPickLine.id)
        .join(WmsPickSession, WmsPickSession.id == WmsPickLine.session_id)
        .where(
            WmsPickLine.document_line_id == line_id,
            WmsPickLine.status.in_(['picked', 'short']),
            WmsPickSession.organization_id == org_id,
            WmsPickSession.status.in_(['active', 'paused']),
        )
        .limit(1)
    )
    return received is not None


async def set_line_target_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    line_id: UUID,
    target_location_id: UUID | None,
    user_id: UUID,
) -> Document:
    """Name (or clear) the shelf one receipt line will land on.

    A receipt document only: dispatch and transfer lines speak of shelves
    goods LEAVE, and their documents already carry the destination. Open to
    DRAFT and CONFIRMED — the question comes up at the shelf, after the
    document was confirmed — and closed once the goods are booked. A named
    shelf has to be a real, still-listed one in this organization; the same
    function answers that for a rule's target and for the document's.
    """
    from . import document_types as dt

    doc = await get_or_raise(db, org_id, doc_id)
    await _check_document_period_open(db, org_id, doc)
    if not dt.is_receipt(doc.type):
        raise ServiceRejectionError('line_target_receipt_only')
    if doc.status not in (DocumentStatus.DRAFT.value, DocumentStatus.CONFIRMED.value):
        raise ServiceRejectionError('document_update_status')

    line = next((line for line in doc.lines if line.id == line_id), None)
    if line is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException('document_line')
    if await _received_in_open_session_async(db, org_id, line.id):
        raise ServiceRejectionError('line_target_already_received')

    if target_location_id is not None:
        await validate_location_async(
            db,
            org_id,
            target_location_id,
            internal_only=True,
            active_only=True,
        )
    old_target = line.target_location_id
    line.target_location_id = target_location_id
    # Naming the shelf is a planning decision somebody made: the log keeps
    # both shelves, because the answer "somewhere else" is not one.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'type': doc.type,
            'fields': ['target_location_id'],
            'line_id': str(line_id),
            'old_target_location_id': str(old_target) if old_target else None,
            'new_target_location_id': (
                str(target_location_id) if target_location_id else None
            ),
        },
    )
    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


#: Where a module's fields may still change: before the goods are booked.
#: A confirmed document is still open — a pre-post check may be waiting for
#: the very field the reader is about to fill in.
_FIELDS_OPEN = frozenset(
    {
        DocumentStatus.DRAFT.value,
        DocumentStatus.PENDING_APPROVAL.value,
        DocumentStatus.CONFIRMED.value,
    }
)


async def set_module_meta_data_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    module: str,
    values: dict[str, Any],
    user_id: UUID,
    *,
    line_id: UUID | None = None,
) -> Document:
    """Write one module's own fields on a document, or on one of its lines.

    Only *module*'s key changes — another module's fields on the same record
    stay as they are — and empty *values* remove the key. The row is taken
    first, so two modules writing at once do not lose each other's key.
    Flushes; the caller commits.
    """
    doc = await _get_doc_for_update(db, org_id, doc_id)
    await _check_document_period_open(db, org_id, doc)
    if doc.status not in _FIELDS_OPEN:
        raise ServiceRejectionError('document_fields_closed')
    target: Document | DocumentLine = doc
    if line_id is not None:
        line = next((line for line in doc.lines if line.id == line_id), None)
        if line is None:
            raise NotFoundException('document_line')
        target = line
    meta = dict(target.meta_data or {})
    if values:
        meta[module] = values
    else:
        meta.pop(module, None)
    # A new dict, not the old one changed in place: the column is plain
    # JSONB, so only an assignment marks it as changed.
    target.meta_data = meta or None
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'type': doc.type,
            'fields': ['meta_data'],
            'module': module,
            'line_id': str(line_id) if line_id else None,
        },
    )
    await db.flush()
    return doc


async def delete_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID | None = None,
) -> None:
    doc = await get_or_raise(db, org_id, doc_id)
    # A draft is a plan nobody confirmed: nothing was promised, no number
    # was given out, and throwing it away leaves the register whole. A
    # cancelled document is the opposite — it is an act that happened, with
    # a number the register handed out (or an identifier nothing consumed),
    # and deleting it erases the record of the act along with the paper.
    if doc.status != DocumentStatus.DRAFT.value:
        raise ServiceRejectionError('document_delete_status')

    # A module that holds documents drops what it keeps about this one: the
    # approvals module withdraws a request still open on it, so its queue
    # does not ask anybody to decide on a document that is gone. A draft is
    # never held, so this is defence in depth — a request raised on the same
    # action before a cancel cascade ran would otherwise linger.
    await notify_withdrawn_async(db, org_id, doc_id, user_id)

    # The record itself is about to be gone: the number has to travel in the
    # snapshot, or the entry answers an id nobody can look up.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'type': doc.type,
            'status': doc.status,
        },
    )
    await db.delete(doc)
    await db.flush()
