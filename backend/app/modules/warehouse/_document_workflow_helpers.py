from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import PartnerDTO
from app.core.exceptions import AppException, ServiceRejectionError
from app.core.print_identity import issuer_snapshot
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from . import document_types as dt
from ._over_receipt import SURPLUS_CODE, assert_over_receipt_allowed_async
from ._wms_line_utils import _resolve_uom_symbol
from .document_profile_service import resolve_document_tax_rate
from .inventory_period_service import check_period_not_closed_async
from .models import QUARANTINE_CODES, Document, DocumentLine, TaxHandling
from .schemas import DocumentComplete
from .tax_rate_assignment_service import product_tax_rates_async


class ReceiptExpiryRequiredError(AppException):
    """400 — a FEFO receipt line would go on the shelf undated.

    The receiving screens ask this question per scan and per tap; the
    completion is the last door onto stock and the one an API caller
    reaches directly, so it answers with the same question in a structured
    envelope: a stable code and one row per undated line, so a client can
    ask for each date without parsing the sentence.
    """

    def __init__(self, lines: list[dict[str, Any]]) -> None:
        super().__init__(
            status_code=400,
            code='RECEIPT_EXPIRY_REQUIRED',
            message=get_error_message(
                'document_receipt_lines_need_expiry',
                get_current_lang(),
                lines=', '.join(
                    f'{row["line_number"]} ({row["product"]})' for row in lines
                ),
            ),
            extra={'lines': lines},
        )


def keep_line_tracking(
    line: DocumentLine,
    batch_number: str | None,
    expiry_date: date | None,
) -> None:
    """Put a lot and expiry that arrived with a booking on the line it books.

    Only where the line has none of its own: a date written earlier — by a
    receiving scan, a tap, or an earlier completion answer — is never
    restated by a later door.
    """
    if batch_number and line.batch_number is None:
        line.batch_number = batch_number.strip()
    if expiry_date is not None and line.expiry_date is None:
        line.expiry_date = expiry_date


async def _apply_line_tax_rates(
    db: AsyncSession, org_id: UUID, profile: Any, lines: list[DocumentLine]
) -> None:
    """Put a tax rate on every line that names none.

    The goods answer first: the rate their product names, or its category
    (``product_tax_rates_async``), so a receipt of bread and of cleaning
    agents carries two rates nobody typed. A line whose goods name none
    takes the document's rate under ``SIMPLE_RATE``: the profile's explicit
    entry, the organization's country when the profile states no opinion.
    A profile that charges no tax leaves every line untaxed, and so does a
    country with no row and no profile entry — an untaxed document is worth
    its net.
    """
    if profile.tax_handling == TaxHandling.NONE:
        return
    open_lines = [line for line in lines if line.tax_rate is None]
    if not open_lines:
        return
    named = await product_tax_rates_async(
        db, org_id, (line.product_template_id for line in open_lines)
    )
    default = (
        await resolve_document_tax_rate(db, org_id, profile)
        if profile.tax_handling == TaxHandling.SIMPLE_RATE
        else None
    )
    for line in open_lines:
        rate = named.get(line.product_template_id) if line.product_template_id else None
        line.tax_rate = rate if rate is not None else default


async def _check_document_period_open(
    db: AsyncSession,
    org_id: UUID,
    doc: Document,
) -> None:
    """The month a document belongs to has to be open to act on it."""
    await check_period_not_closed_async(
        db, org_id, doc.scheduled_date or doc.created_at.date()
    )


def _build_partner_snapshot(partner: PartnerDTO) -> dict[str, Any]:
    return {
        'name': partner.name,
        'code': partner.code,
        'tax_id': partner.tax_id,
        'address': partner.address,
        'email': partner.email,
        'phone': partner.phone,
    }


def _build_print_snapshot(doc: Document, organization: Any) -> dict[str, Any]:
    """What the printout states about the issuer and the places, as of now."""
    return {
        'issuer': issuer_snapshot(organization),
        'source_location': doc.source_location.name if doc.source_location else None,
        'target_location': doc.target_location.name if doc.target_location else None,
    }


def _default_execution_quantities(lines: Iterable[DocumentLine]) -> None:
    """Complete every line nobody answered for as delivered in full.

    A line that names a discrepancy and is still short of what was ordered is
    an answer somebody gave — a picker or receiver who skipped it, or took
    less and said why. Filling it in and clearing the reason signed those
    goods off as delivered, raised no backorder, and put stock on the books
    that never arrived.

    A code left on a line that reached exactly its quantity is stale — short,
    then scanned to full — and clearing it is the point of the second branch.
    A line that stands above its quantity is the opposite: the surplus is an
    exception, and its reason survives completion the way a shortage's does.
    """
    for line in lines:
        done = line.done_quantity or Decimal('0')
        held = line.held_quantity or Decimal('0')
        if line.discrepancy_code and done < line.expected_quantity:
            continue
        if done == 0:
            line.done_quantity = line.expected_quantity
        if line.done_quantity == line.expected_quantity and not held:
            # A line that says part of what arrived is held back keeps the
            # code that says why, even when the delivery itself is full.
            line.discrepancy_code = None
            line.discrepancy_reason = None
        elif line.done_quantity > line.expected_quantity:
            if not line.discrepancy_code:
                line.discrepancy_code = SURPLUS_CODE
                line.discrepancy_reason = None


def _refuse_a_held_quantity_the_line_cannot_mean(
    doc: Document,
    done_quantity: Decimal,
    held_quantity: Decimal,
    discrepancy_code: str | None,
) -> None:
    """The three things a held quantity has to be to be believable.

    It is part of what arrived, so it cannot be negative or exceed the done
    quantity. It is goods coming in, so only a receipt may state it. And it
    is an exception, so it must name why — Damage or Quality hold, the codes
    that mean "not for the shelf".
    """
    if held_quantity < 0:
        raise ServiceRejectionError(
            'document_held_quantity_negative', quantity=held_quantity
        )
    if held_quantity > done_quantity:
        raise ServiceRejectionError(
            'document_held_quantity_above_received',
            quantity=held_quantity,
            received=done_quantity,
        )
    if held_quantity and not dt.is_receipt(doc.type):
        raise ServiceRejectionError('document_held_quantity_needs_receipt')
    if held_quantity and discrepancy_code not in QUARANTINE_CODES:
        raise ServiceRejectionError('document_held_quantity_needs_code')


def _require_every_line_answered(
    doc: Document, answered: Collection[UUID] = ()
) -> None:
    """Refuse a completion that would book unanswered lines as delivered.

    The execution panel names every line and a scanning session resolves each
    one before it closes, so a line still short of what it expects, with no
    reason, means nobody answered for it: a shortfall is a decision someone
    made, and the reason is the record that someone did. A client that sends no body — an integration, a
    script, a webhook consumer — would have those lines booked in full and
    stock put on the books that never arrived; so would a body that names
    only some lines. It has to say so explicitly (``complete_as_planned``).

    ``answered`` names the lines the body answered — a quantity of zero is
    still an answer. A line the body leaves out keeps whatever a session
    already wrote for it; one with nothing written and no reason is the
    refusal. A correction has no per-line answers: its lines are the deltas
    themselves.
    """
    if doc.type == 'CORRECTION':
        return

    def reached(line: DocumentLine) -> bool:
        return (line.done_quantity or Decimal('0')) >= line.expected_quantity > 0

    unanswered = [
        line.line_number
        for line in doc.lines
        if line.id not in answered and not line.discrepancy_code and not reached(line)
    ]
    if unanswered:
        raise ServiceRejectionError(
            'document_complete_unanswered_lines',
            lines=', '.join(str(n) for n in unanswered),
        )


def _settle_an_execution_line(
    doc: Document,
    line: DocumentLine,
    *,
    done_quantity: Decimal,
    held_quantity: Decimal,
    discrepancy_code: str | None,
    discrepancy_reason: str | None,
    batch_number: str | None,
    expiry_date: date | None,
) -> None:
    """Settle one line on the quantity, reason and tracking it was answered with.

    Raises a rejected business rule rather than booking a quantity the line
    cannot mean; every refusal here is one completion's own answer.
    """
    is_correction = doc.type == 'CORRECTION'
    if not is_correction:
        if done_quantity < 0:
            raise ServiceRejectionError(
                'document_done_quantity_negative', quantity=done_quantity
            )
        _refuse_a_held_quantity_the_line_cannot_mean(
            doc, done_quantity, held_quantity, discrepancy_code
        )
        # A receipt may go past its expectation — the tolerance gate in
        # ``complete_document`` (or the order guard for a line that names
        # an order line) decides whether it may. Every other type still
        # stops here, and a receipt line only has to say why, exactly as
        # a partial does.
        if done_quantity > line.expected_quantity and not dt.is_receipt(doc.type):
            raise ServiceRejectionError(
                'document_done_quantity_above_expected',
                quantity=done_quantity,
                expected=line.expected_quantity,
            )
        if done_quantity < line.expected_quantity and not discrepancy_code:
            raise ServiceRejectionError('document_partial_needs_discrepancy_code')
        if done_quantity > line.expected_quantity and not discrepancy_code:
            discrepancy_code = SURPLUS_CODE
    else:
        # Corrections use signed deltas; bound by absolute expected.
        if abs(done_quantity) > abs(line.expected_quantity):
            raise ServiceRejectionError(
                'document_correction_above_expected',
                quantity=done_quantity,
                expected=line.expected_quantity,
            )
        # the delta is signed, and completing a correction is not
        # the place to reverse its direction. A body that disagrees with
        # the document is a client bug, not a decrease turned increase.
        if done_quantity and (done_quantity > 0) != (line.expected_quantity > 0):
            raise ServiceRejectionError(
                'document_correction_sign_mismatch',
                quantity=done_quantity,
                expected=line.expected_quantity,
            )
    line.done_quantity = done_quantity
    line.held_quantity = Decimal('0') if is_correction else held_quantity
    # A held quantity is an exception even when the delivery is full: the
    # line has to keep the code that says why those goods are not for the
    # shelf, or the next reader sees a complete line and nothing held.
    says_something = done_quantity != line.expected_quantity or held_quantity > Decimal(
        '0'
    )
    line.discrepancy_code = (
        discrepancy_code if (not is_correction and says_something) else None
    )
    line.discrepancy_reason = (
        discrepancy_reason if (not is_correction and says_something) else None
    )
    # The lot and expiry that rode along with this answer land on the line
    # exactly as a receiving scan's do.
    keep_line_tracking(line, batch_number, expiry_date)


def _apply_execution_quantities(
    doc: Document,
    execution_data: DocumentComplete | None,
) -> None:
    if execution_data is None or not execution_data.lines:
        if not (execution_data and execution_data.complete_as_planned):
            _require_every_line_answered(doc)
        _default_execution_quantities(doc.lines)
        return

    doc_line_ids = {line.id for line in doc.lines}
    execution_by_line: dict[UUID, Decimal] = {}
    held_by_line: dict[UUID, Decimal] = {}
    discrepancy_code_by_line: dict[UUID, str | None] = {}
    discrepancy_reason_by_line: dict[UUID, str | None] = {}
    batch_by_line: dict[UUID, str] = {}
    expiry_by_line: dict[UUID, date] = {}

    for execution_line in execution_data.lines:
        if execution_line.line_id not in doc_line_ids:
            raise ServiceRejectionError('document_execution_line_foreign')
        if execution_line.line_id in execution_by_line:
            raise ServiceRejectionError('document_execution_line_repeated')
        execution_by_line[execution_line.line_id] = execution_line.done_quantity
        if execution_line.batch_number:
            batch_by_line[execution_line.line_id] = execution_line.batch_number.strip()
        if execution_line.expiry_date is not None:
            expiry_by_line[execution_line.line_id] = execution_line.expiry_date
        held_by_line[execution_line.line_id] = execution_line.held_quantity or Decimal(
            '0'
        )
        discrepancy_code_by_line[execution_line.line_id] = (
            execution_line.discrepancy_code
        )
        discrepancy_reason_by_line[execution_line.line_id] = (
            execution_line.discrepancy_reason.strip()
            if execution_line.discrepancy_reason
            else None
        )

    if execution_data.complete_as_planned or doc.type == 'CORRECTION':
        # Settle the lines the body leaves out the way a bodiless completion
        # does: an earlier answer stands, and a line with none is booked as
        # planned. The flag is the caller saying that is what it means; a
        # correction needs no flag, its lines being the deltas themselves.
        _default_execution_quantities(
            line for line in doc.lines if line.id not in execution_by_line
        )
    else:
        _require_every_line_answered(doc, execution_by_line)

    for line in doc.lines:
        answered = line.id in execution_by_line
        # A line nobody answered for keeps what it already says was held back;
        # a line answered for says so itself. Treating silence as zero would
        # release goods a receiving session had just quarantined because the
        # completion body happened not to repeat the line.
        _settle_an_execution_line(
            doc,
            line,
            done_quantity=execution_by_line.get(
                line.id, line.done_quantity or Decimal('0')
            ),
            held_quantity=held_by_line.get(line.id, line.held_quantity or Decimal('0')),
            discrepancy_code=(
                discrepancy_code_by_line.get(line.id)
                if answered
                else line.discrepancy_code
            ),
            discrepancy_reason=(
                discrepancy_reason_by_line.get(line.id)
                if answered
                else line.discrepancy_reason
            ),
            batch_number=batch_by_line.get(line.id),
            expiry_date=expiry_by_line.get(line.id),
        )


async def assert_receipt_lines_dated_async(
    db: AsyncSession, org_id: UUID, doc: Document, *, as_planned: bool = False
) -> None:
    """Ask for the expiry of every FEFO line a receipt is about to bring in.

    The scan and the tap doors ask it before booking; completion is the
    last door onto stock and the one an API caller reaches directly, so the
    same rule is asked here for the lines the document does not date. A line
    may name the product itself or only the record it receives into — the
    record's template answers for it either way. The lot may stay empty —
    under FEFO an undated record sorts behind every dated one, which is what
    this refusal exists to prevent.

    ``as_planned`` weighs the lines by what the document plans to bring
    (``expected_quantity``) rather than the quantity an execution has
    answered (``done_quantity``): a draft posted in one press is completed
    as planned, and holds no answers yet. The press asks before the posting
    can be parked behind an approval, where nobody stands to answer.
    """
    if not dt.is_receipt(doc.type) or doc.stock_already_applied:
        return

    def brought(line: DocumentLine) -> Decimal:
        quantity = line.expected_quantity if as_planned else line.done_quantity
        return quantity or Decimal('0')

    candidates = [
        line for line in doc.lines if line.expiry_date is None and brought(line) > 0
    ]
    if not candidates:
        return
    # Resolve every line's product before asking for the templates: a line
    # that names only a record carries no template of its own, and looking
    # its template up in a batch fetched without it would miss it.
    template_id_by_line: dict[UUID, UUID | None] = {}
    for line in candidates:
        template_id = line.product_template_id
        if template_id is None and line.item_id is not None:
            item = await core_api.items.get_async(db, org_id, line.item_id)
            template_id = item.template_id if item is not None else None
        template_id_by_line[line.id] = template_id
    templates = await core_api.product_templates.get_many_async(
        db,
        org_id,
        [
            template_id
            for template_id in template_id_by_line.values()
            if template_id is not None
        ],
    )
    undated: list[dict[str, Any]] = []
    for line in candidates:
        template_id = template_id_by_line[line.id]
        template = templates.get(template_id) if template_id is not None else None
        if template is None:
            continue
        if core_api.stock.resolve_removal_strategy(template) != 'FEFO':
            continue
        undated.append(
            {
                'line_id': str(line.id),
                'line_number': line.line_number,
                'product': line.name or '',
            }
        )
    if undated:
        raise ReceiptExpiryRequiredError(undated)


async def assert_receipt_over_receipts_allowed_async(
    db: AsyncSession,
    org_id: UUID,
    doc: Document,
    *,
    may_exceed: bool,
) -> None:
    """Weigh every over-received receipt line the order guard does not own.

    An order-linked line is measured against what is left on its order line
    by the orders module's pre-post check. A line whose expectation is only a
    count somebody typed has nothing to exceed. Everything else on a receipt is
    measured against its own expected quantity, through the organization's
    over-receipt tolerance and the caller's permission —
    the same gate the ramp asked, asked again on the way out because the
    completion is free to name a different number.
    """
    if not dt.is_receipt(doc.type):
        return
    for line in doc.lines:
        if line.source_po_line_id is not None or line.expected_is_count:
            continue
        done = line.done_quantity or Decimal('0')
        if done > line.expected_quantity:
            await assert_over_receipt_allowed_async(
                db,
                org_id,
                quantity=done,
                basis=line.expected_quantity,
                may_exceed=may_exceed,
                product=line.name,
            )


def _place(
    place: Any, place_id: UUID | None, known: dict[UUID, tuple[str | None, str]]
) -> None:
    """Remember a shelf the document or a line already carries loaded."""
    if place_id is not None and place is not None:
        known.setdefault(place_id, (place.short_code, place.name))


async def _load(db: AsyncSession, obj: Any, *names: str) -> None:
    """Load the relationships of a row that was flushed in this session.

    A row created and flushed here has none of its ``selectin`` relationships
    yet, and reading one from async code would raise instead of loading.
    """
    state = sa_inspect(obj, raiseerr=False)
    missing = [name for name in names if state is not None and name in state.unloaded]
    if missing:
        await db.refresh(obj, missing)


def _line_shelves(doc: Document, line: DocumentLine) -> tuple[UUID | None, UUID | None]:
    """The shelf a line's goods left and the one they landed on.

    The direction is the document's. A dispatch or a scrap takes from a shelf
    and puts nothing on another: the shelf the executor wrote into
    ``executed_location_id`` is the one it took from, and the goods end
    outside. Everything else leaves the line's own pin or the document's
    source and lands on the shelf it executed to, else the one named ahead of
    execution, else the document's.
    """
    if dt.is_dispatch(doc.type) or dt.is_scrap(doc.type):
        source_id = (
            line.executed_location_id
            or line.source_location_id
            or doc.source_location_id
            or (line.item.location_id if line.item is not None else None)
        )
        return source_id, None
    return (
        line.source_location_id or doc.source_location_id,
        line.executed_location_id or line.target_location_id or doc.target_location_id,
    )


async def _lots_drawn_by_line(
    db: AsyncSession, org_id: UUID, doc: Document
) -> dict[UUID, list[tuple[UUID | None, Decimal]]]:
    """The batches an outbound document's lines took, read off its journal.

    A dispatch or a scrap that names no batch draws across whatever the
    records hold, in the order the draw ranks them, so the lot of the item a
    line points at says nothing about what left. The movements the draw wrote
    do. They carry the document, not the line: the lines of one product take
    them in order, each as much as it posted.
    """
    if not (dt.is_dispatch(doc.type) or dt.is_scrap(doc.type)):
        return {}
    moves = await core_api.stock_moves.list_by_reference_async(
        db, org_id, 'document', doc.id, limit=5000
    )
    pending: dict[UUID, list[list[Any]]] = {}
    for move in sorted(moves, key=lambda m: m.created_at or datetime.min):
        if move.from_location_id is not None:
            pending.setdefault(move.product_template_id, []).append(
                [move.lot_id, move.quantity]
            )
    drawn: dict[UUID, list[tuple[UUID | None, Decimal]]] = {}
    for line in doc.lines:
        product_id = line.product_template_id or (
            line.item.template_id if line.item is not None else None
        )
        queue = pending.get(product_id) if product_id else None
        if not queue or not line.done_quantity:
            continue
        need = await core_api.uoms.to_stock_uom_async(
            db, org_id, product_id, line.done_quantity, line.uom_id
        )
        parts: list[tuple[UUID | None, Decimal]] = []
        while queue and need > 0:
            lot_id, quantity = queue[0]
            taken = min(quantity, need)
            parts.append((lot_id, taken))
            need -= taken
            if taken == quantity:
                queue.pop(0)
            else:
                queue[0][1] = quantity - taken
        if parts:
            drawn[line.id] = parts
    return drawn


async def _line_details_async(
    db: AsyncSession, org_id: UUID, doc: Document
) -> list[list[dict[str, Any]]]:
    """What each line of ``doc`` is about: product, lot, shelves and unit.

    A subscriber that reacts after posting reads the stock effect off these
    instead of fetching the document. The shelves follow the posting
    direction (``_line_shelves``). A lot is the one the line names, else the
    one the stock record it moves carries, and its id only once the batch
    exists — a confirmed receipt has not created it yet. A delivery or a
    scrap says instead what its draw took (``_lots_drawn_by_line``): a line
    that took from several batches answers with one entry per batch, each
    with its own ``done_quantity`` (the expectation stays on the first).
    """
    known: dict[UUID, tuple[str | None, str]] = {}
    await _load(db, doc, 'source_location', 'target_location')
    _place(doc.source_location, doc.source_location_id, known)
    _place(doc.target_location, doc.target_location_id, known)
    lots: dict[UUID | None, list[Any]] = {}
    for line in doc.lines:
        await _load(
            db,
            line,
            'item',
            'product_template',
            'uom',
            'executed_location',
            'source_location',
        )
    drawn = await _lots_drawn_by_line(db, org_id, doc)
    details: list[list[dict[str, Any]]] = []
    for line in doc.lines:
        _place(line.executed_location, line.executed_location_id, known)
        _place(line.source_location, line.source_location_id, known)
        source_id, target_id = _line_shelves(doc, line)
        for place_id in (source_id, target_id):
            if place_id is not None and place_id not in known:
                found = await core_api.locations.get_async(db, org_id, place_id)
                known[place_id] = (
                    (found.short_code, found.name) if found else (None, '')
                )

        product_id = line.product_template_id or (
            line.item.template_id if line.item is not None else None
        )
        parts: list[tuple[UUID | None, Decimal | None]] = [
            (lot_id, quantity) for lot_id, quantity in drawn.get(line.id, [])
        ] or [(None, None)]
        typed = line.serial_number or line.batch_number
        record_lot_id = line.item.lot_id if line.item is not None else None
        line_details: list[dict[str, Any]] = []
        for index, (drawn_lot_id, drawn_quantity) in enumerate(parts):
            if drawn_quantity is not None:
                wanted_id, wanted_name = drawn_lot_id, None
            else:
                wanted_id, wanted_name = (
                    (None, typed) if typed else (record_lot_id, None)
                )
            lot = None
            if product_id is not None and (wanted_id or wanted_name):
                if product_id not in lots:
                    lots[product_id] = await core_api.stock.list_lots_async(
                        db, org_id, product_id
                    )
                lot = next(
                    (
                        candidate
                        for candidate in lots[product_id]
                        if candidate.id == wanted_id or candidate.name == wanted_name
                    ),
                    None,
                )
            detail: dict[str, Any] = {
                'product_id': str(product_id) if product_id else None,
                'product_code': line.sku,
                'lot_id': str(lot.id) if lot else None,
                'lot_number': lot.name if lot else (wanted_name or None),
                'source_location_id': str(source_id) if source_id else None,
                'source_location_code': known[source_id][0] or known[source_id][1]
                if source_id
                else None,
                'target_location_id': str(target_id) if target_id else None,
                'target_location_code': known[target_id][0] or known[target_id][1]
                if target_id
                else None,
                'unit': _resolve_uom_symbol(line),
            }
            if drawn_quantity is not None:
                detail['done_quantity'] = float(drawn_quantity)
                if index:
                    detail['expected_quantity'] = 0.0
            line_details.append(detail)
        details.append(line_details)
    return details


async def build_document_event_payload(
    db: AsyncSession,
    doc: Document,
    org_id: UUID,
) -> dict[str, Any]:
    """Shared payload for the ``document.*`` lifecycle events.

    CONFIRMED, COMPLETED, CANCELLED, SHIPPED and the rework-cancel in
    ``_document_rework_service`` all publish the same per-line shape.

    Key order matches what COMPLETED emitted before extraction — ``lines``
    entries stay ``source_po_line_id``, ``done_quantity``,
    ``expected_quantity`` — and the keys that say what moved (see
    ``_line_details_async``) follow them, so the serialised payload only
    grows at the end of every line.
    """
    details = await _line_details_async(db, org_id, doc)
    lines: list[dict[str, Any]] = []
    for line, parts in zip(doc.lines, details, strict=True):
        for detail in parts:
            entry: dict[str, Any] = {
                'source_po_line_id': str(line.source_po_line_id)
                if line.source_po_line_id
                else None,
                'done_quantity': float(line.done_quantity or 0),
                'expected_quantity': float(line.expected_quantity or 0),
                **detail,
            }
            lines.append(entry)

    return {
        'organization_id': str(org_id),
        'document_id': str(doc.id),
        'document_type': doc.type,
        'lines': lines,
    }
