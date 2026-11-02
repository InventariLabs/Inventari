from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType, CountDifferenceDTO
from app.core.db_utils import acquire_advisory_lock
from app.core.events import emit_transactional_safe
from app.core.exceptions import ServiceRejectionError, StockUnavailableError
from app.core.public_api import core_api

from . import document_types as dt
from ._document_workflow_helpers import build_document_event_payload
from ._line_reversals import (
    reversible_quantities_async,
    stock_the_document_posted_was_used_async,
)
from ._over_receipt import assert_over_receipt_allowed_async
from ._po_receipt_guard import order_line_remaining_async
from .document_numbering_service import generate_number, temporary_number
from .document_profile_service import get_or_create_profile, resolve_document_currency
from .document_type_config_service import get_type_config
from .document_value_service import recompute_document_values
from .events import DocumentEvent
from .models import (
    CorrectionReasonCode,
    Document,
    DocumentLine,
    DocumentRelation,
    DocumentStatus,
    DocumentType,
)

#: The types one press of "Undo" reverses: a receipt, an issue, a move or a
#: write-off — "damaged or expired" is one of the issue screen's purposes, and
#: a wrong press there is as much a typo as a wrong customer. Less scrapped
#: puts the goods back, the way less issued does (``correction_sign``). A
#: correction or a stock take restates a difference of its own, so a mistake
#: in either is another document, not the absence of the first.
UNDOABLE_TYPES: frozenset[str] = frozenset(
    {dt.IN, dt.INTERNAL_IN, dt.OUT, dt.INTERNAL_OUT, dt.INT, dt.SCRAP}
)

#: Refusals that mean the stock the original posted is no longer all there:
#: a record or a shelf left short, or a line something else already restated.
#: They reach the reader as one sentence about an undo, with the way out.
_UNDO_STOCK_KEYS: frozenset[str] = frozenset(
    {
        'document_correction_would_go_negative',
        'document_insufficient_stock',
        'document_insufficient_stock_record_elsewhere',
        'document_return_quantity_exceeds_left',
        'transfer_more_than_the_record_holds',
    }
)


def _line_number_of(delta: dict[str, Any]) -> int:
    """The number of the original line a correction delta restates."""
    number = delta.get('original_line_number') or delta.get('line_number')
    assert number is not None
    return int(number)


async def _read_correction_back(db: AsyncSession, correction_id: UUID) -> Document:
    """Read the correction the way a GET would, not by refreshing the object
    we just built.

    Its lines sit in the identity map with their unit never loaded, and
    neither a refresh nor a plain re-select re-fires an eager loader on an
    instance that is already there — so the response serializer reached for
    ``line.uom`` and found a lazy load on an async session. A correction of a
    line that named a unit crashed on the way out, after it had already been
    written.
    """
    return (
        (
            await db.execute(
                select(Document)
                .options(selectinload(Document.lines))
                .where(Document.id == correction_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .one()
    )


async def create_correction(
    db: AsyncSession,
    corrects_document_id: UUID,
    correction_lines: list[dict[str, Any]],
    org_id: UUID,
    user_id: UUID,
    notes: str | None = None,
    reason_code: str | None = None,
    *,
    may_exceed_over_receipt: bool = False,
    relation_type: str = 'corrects',
) -> Document:
    await acquire_advisory_lock(db, f'document_correction:{corrects_document_id}')
    result = await db.execute(
        select(Document).where(
            Document.id == corrects_document_id,
            Document.organization_id == org_id,
        )
    )
    original = result.scalars().first()
    if not original:
        raise ServiceRejectionError('document_not_found')
    if original.status != DocumentStatus.COMPLETED.value:
        raise ServiceRejectionError('document_correction_requires_completed')
    # A type with no direction (an adjustment) is refused here, where the
    # correction would be written, and not at completion, where it used to
    # fail after it had already been saved and confirmed.
    dt.correction_sign(original.type)

    original_lines_by_number: dict[int, DocumentLine] = {
        line.line_number: line for line in original.lines
    }

    if not correction_lines:
        raise ServiceRejectionError('document_correction_no_lines')

    for delta in correction_lines:
        ln = delta.get('original_line_number') or delta.get('line_number')
        if ln not in original_lines_by_number:
            raise ServiceRejectionError(
                'document_original_line_missing', line=ln, number=original.number
            )

    # the negative side is bounded by what is actually still there —
    # what the line executed, less what earlier corrections and returns have
    # already taken off it. Bounding it by the original figure meant a
    # delivery of ten accepted a correction of minus ten twice over.
    # Positive deltas stay unbounded on purpose (over-receipt corrections).
    left_on_line = await reversible_quantities_async(
        db,
        org_id,
        [
            original_lines_by_number[_line_number_of(delta)]
            for delta in correction_lines
        ],
    )
    for delta in correction_lines:
        ln = _line_number_of(delta)
        original_line = original_lines_by_number[ln]
        qty_delta = Decimal(str(delta['quantity_delta']))
        # The unit's own step, the same question ``build_document_line`` asks
        # of every line that comes in through the document form. This path
        # builds its lines by hand and so asked nobody: a delta of 1.5 on a
        # line counted in pieces was saved, confirmed and executed, and half
        # a piece reached the record, the movement ledger and the valuation.
        # The magnitude is what gets measured — a delta is signed by design,
        # and the precision gate refuses a negative number outright.
        if original_line.uom_id is not None:
            await core_api.uoms.validate_quantity_precision_async(
                db, original_line.uom_id, abs(qty_delta), org_id
            )
        left = left_on_line[original_line.id]
        if left + qty_delta < 0:
            raise ServiceRejectionError(
                'document_correction_below_zero',
                delta=qty_delta,
                line=ln,
                left=left,
                done=original_line.done_quantity,
            )
        # A positive correction raises what the receipt brought, so it
        # passes the same gate the ramp does: within the organization's
        # over-receipt tolerance anyone may record it, past that only a
        # holder of ``warehouse:receive_over_tolerance``. An order-linked
        # line is measured against what is left on its order line — the
        # figure the order guard will weigh again when the correction is
        # confirmed and completed.
        if qty_delta > 0 and (
            dt.is_receipt(original.type) or original_line.source_po_line_id is not None
        ):
            remaining: Decimal | None = None
            if original_line.source_po_line_id is not None:
                remaining = await order_line_remaining_async(
                    db, org_id, original_line, exclude_doc_id=None
                )
            if remaining is not None:
                delta_in_stock = await core_api.uoms.to_stock_uom_async(
                    db,
                    org_id,
                    original_line.product_template_id,
                    qty_delta,
                    original_line.uom_id,
                )
                await assert_over_receipt_allowed_async(
                    db,
                    org_id,
                    quantity=delta_in_stock,
                    basis=remaining,
                    may_exceed=may_exceed_over_receipt,
                )
            else:
                await assert_over_receipt_allowed_async(
                    db,
                    org_id,
                    quantity=left + qty_delta,
                    basis=original_line.expected_quantity,
                    may_exceed=may_exceed_over_receipt,
                )

    # A correction is a draft like any other: it carries an identifier until
    # confirmation draws its number (see document_numbering_service).
    number = temporary_number()

    correction = Document(
        organization_id=org_id,
        type=DocumentType.CORRECTION.value,
        number=number,
        status=DocumentStatus.DRAFT.value,
        corrects_document_id=corrects_document_id,
        partner_id=original.partner_id,
        source_location_id=original.source_location_id,
        target_location_id=original.target_location_id,
        external_reference=original.number,
        notes=notes,
        reason_code=reason_code,
        # Other modules' fields restate the document's own: a certificate or
        # a customs code a module required on the original is the same on
        # the part of it the correction takes back.
        meta_data=original.meta_data,
        created_by=user_id,
        # The money of a correction is the money of the document it corrects,
        # not the organization's current default: restating part of a EUR
        # receipt in USD would be a different claim. Built by hand, this header
        # was the one that carried no currency at all, and a single such
        # document made the register read as multi-currency and drop the
        # month's totals.
        currency=original.currency,
    )
    db.add(correction)
    await db.flush()

    for i, delta in enumerate(correction_lines, start=1):
        ln = delta.get('original_line_number') or delta.get('line_number')
        assert ln is not None
        original_line = original_lines_by_number[ln]
        qty_delta = Decimal(str(delta['quantity_delta']))

        corr_line = DocumentLine(
            document_id=correction.id,
            item_id=original_line.item_id,
            product_template_id=original_line.product_template_id,
            name=original_line.name,
            brand=original_line.brand,
            barcode=original_line.barcode,
            quantity=qty_delta,
            expected_quantity=qty_delta,
            done_quantity=Decimal('0'),
            uom_id=original_line.uom_id,
            batch_number=original_line.batch_number,
            serial_number=original_line.serial_number,
            unit_price=original_line.unit_price,
            tax_rate=original_line.tax_rate,
            notes=delta.get('notes'),
            line_number=i,
            corrects_line_id=original_line.id,
            # The order provenance travels with the line. Without it the
            # order never saw the correction: ``quantity_received`` is
            # recomputed from lines that name their order line, and the
            # order guard had nothing to weigh — so a positive correction
            # added stock and left the order reading the old figure.
            source_po_line_id=original_line.source_po_line_id,
            meta_data=original_line.meta_data,
        )
        db.add(corr_line)

    # Every other type has its values computed on creation; this one copied the
    # unit prices and stopped there, so a correction showed a partner an
    # invoice with no amount on it. The refresh is what makes the lines
    # readable — the collection was never loaded, and touching it lazily inside
    # an async session is an error, not a query.
    await db.flush()
    await db.refresh(correction, ['lines'])
    recompute_document_values(correction)

    relation = DocumentRelation(
        source_document_id=correction.id,
        target_document_id=corrects_document_id,
        relation_type=relation_type,
    )
    db.add(relation)

    # The correction names the delivery it corrects, so "who changed the
    # books on this delivery" has an answer without joining anything.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=correction.id,
        snapshot={
            'number': correction.number,
            'type': correction.type,
            'corrects_number': original.number,
            'reason_code': reason_code,
        },
    )

    return await _read_correction_back(db, correction.id)


async def get_corrections_for_document(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(
            Document.corrects_document_id == document_id,
            Document.organization_id == org_id,
        )
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def _create_reversing_return(
    db: AsyncSession,
    original: Document,
    correction_lines: list[dict[str, Any]],
    org_id: UUID,
    user_id: UUID,
) -> Document:
    """Write the transfer's reversal through the return service.

    A transfer moves a record between shelves; a correction of one writes two
    movements and states no record at the shelf the goods come back to, so
    the stock would be counted in the ledger and missing from the records.
    The return door moves the record itself. It is a reversal all the same,
    and the ``reverses`` relation says so beside the ``returns`` one.
    """
    from .document_return_service import create_return
    from .models import ReturnReasonCode

    reversal = await create_return(
        db,
        original_id=original.id,
        lines=[
            {
                'original_line_number': line['original_line_number'],
                'return_quantity': -line['quantity_delta'],
            }
            for line in correction_lines
        ],
        org_id=org_id,
        user_id=user_id,
        # A return carries a reason of its own; "other" is the honest one for
        # a reversal the system writes — the ``reverses`` relation is what
        # names what happened, not a code written into a stored note.
        reason_code=ReturnReasonCode.OTHER.value,
    )
    db.add(
        DocumentRelation(
            source_document_id=reversal.id,
            target_document_id=original.id,
            relation_type='reverses',
        )
    )
    return reversal


async def undo_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
    *,
    may_exceed_over_receipt: bool = False,
) -> Document:
    """Reverse everything a completed document posted, in one transaction.

    The reference data it keeps asking for is read once, and the rows it
    appends are written together when it ends (``posting_batch``).
    """
    async with core_api.stock.posting_scope_async(db):
        return await _undo_document(
            db,
            org_id,
            doc_id,
            user_id,
            may_exceed_over_receipt=may_exceed_over_receipt,
        )


async def _undo_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
    *,
    may_exceed_over_receipt: bool = False,
) -> Document:
    """Reverse everything a completed document posted, in one transaction.

    The way back from a typo on the one-step screen. "Undo" writes the
    correction a reader would otherwise build by hand — one line per line of
    the original, carrying the negative of what is still reversible — and
    posts it through the same confirmation and completion doors as any other
    document. The original keeps its status and its number; the ``reverses``
    relation is what lets its screen name the correction that put the stock
    back.

    What is still reversible is measured against the line, so a line a
    correction or a return has already touched is undone by what is left of
    it rather than refused. What is still on the shelf is measured against
    the movement ledger: stock the original posted that a later movement has
    since taken off that shelf refuses the undo even when another receipt
    has replenished it, because the replacement goods are not the ones the
    original brought. A shortage the completion itself finds is answered
    here too, as one sentence pointing at a correction: the same stock
    question, asked by the door that writes it, instead of a second rule
    that could disagree.

    Nothing commits here — the request owns the transaction, so a refusal
    after the correction was written leaves no draft, no number and no stock
    behind (see ``AGENTS.md`` "Transaction ownership").
    """
    # Taken before the lines are read, so two undos of one document measure
    # the same "what is left" one after the other. The correction service
    # takes the same lock; it is re-entrant inside a transaction.
    await acquire_advisory_lock(db, f'document_correction:{doc_id}')
    original = (
        (
            await db.execute(
                select(Document)
                .options(selectinload(Document.lines))
                .where(Document.id == doc_id, Document.organization_id == org_id)
            )
        )
        .scalars()
        .first()
    )
    if not original:
        raise ServiceRejectionError('document_not_found')
    if dt.normalize(original.type) not in UNDOABLE_TYPES:
        raise ServiceRejectionError('document_undo_type_not_supported')
    if original.status != DocumentStatus.COMPLETED.value:
        raise ServiceRejectionError('document_undo_requires_completed')

    # A transfer is reversed through the return service: the goods themselves
    # have to change shelves, and a transfer correction's two movements state
    # no record at the shelf they come back to (see ``execute_correction``).
    # The return door moves the record back the way the transfer moved it.
    if dt.is_transfer(original.type):
        await acquire_advisory_lock(db, f'document_return:{doc_id}')

    correction_lines: list[dict[str, Any]] = []
    reversible = await reversible_quantities_async(db, org_id, original.lines)
    for line in original.lines:
        left = reversible[line.id]
        if left > 0:
            correction_lines.append(
                {
                    'original_line_number': line.line_number,
                    'quantity_delta': -left,
                }
            )
    if not correction_lines:
        raise ServiceRejectionError('document_undo_nothing_left')
    if await stock_the_document_posted_was_used_async(db, org_id, original):
        raise ServiceRejectionError('document_undo_stock_used')

    # Imported here: the workflow transitions pull the approval and stock
    # graph, and this service is loaded by the router before either is needed.
    from ._document_workflow_transitions import complete_document, confirm_document
    from .schemas import DocumentComplete

    try:
        if dt.is_transfer(original.type):
            reversal = await _create_reversing_return(
                db, original, correction_lines, org_id, user_id
            )
        else:
            reversal = await create_correction(
                db,
                corrects_document_id=doc_id,
                correction_lines=correction_lines,
                org_id=org_id,
                user_id=user_id,
                # An undo is the reader saying the posting was a mistake; it
                # is a correction like any other in the register, and says so.
                reason_code=CorrectionReasonCode.DATA_ENTRY_ERROR.value,
                may_exceed_over_receipt=may_exceed_over_receipt,
                relation_type='reverses',
            )
        reversal = await confirm_document(
            db,
            org_id,
            reversal.id,
            user_id,
            may_exceed_over_receipt=may_exceed_over_receipt,
            # An approval was the only thing between the reversal and the
            # stock: granting it posts the reversal, as it does for the
            # one-step action.
            complete_on_approval=True,
        )
        # An approval standing in front of the reversal parks it: the stock
        # moves when the approval is granted, and the caller says so.
        if reversal.status == DocumentStatus.CONFIRMED.value:
            reversal = await complete_document(
                db,
                org_id,
                reversal.id,
                user_id,
                DocumentComplete(complete_as_planned=True),
                may_exceed_over_receipt=may_exceed_over_receipt,
            )
    except StockUnavailableError as exc:
        # The shelf no longer holds what the original posted. The stock
        # service's sentence already names the product, the shelf and the
        # numbers; answer with it and point at the partial correction.
        raise ServiceRejectionError('document_undo_blocked', reason=str(exc)) from exc
    except ServiceRejectionError as exc:
        # The record itself no longer holds the quantity — the same "used
        # since" answered where the delta is applied, or the return's own
        # bound when another document restated the line first.
        if exc.key in _UNDO_STOCK_KEYS:
            raise ServiceRejectionError('document_undo_stock_used') from exc
        raise

    await db.flush()
    await db.refresh(reversal, attribute_names=['lines'])
    return reversal


async def record_count_differences(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    *,
    location_id: UUID,
    differences: list[CountDifferenceDTO],
    reference: str,
    notes: str | None = None,
) -> Document:
    """The register's copy of what a count changed: one stock adjustment.

    The count has already moved the stock, line by line under its own locks
    and checks, so the document is written as done and marked as a record of
    a movement already applied — nothing here posts a quantity, and nothing
    about it can post one later. It is numbered, completed and announced in
    the caller's transaction: a count that fails to close leaves no document
    behind, and a closed count is never without one.

    The lines are signed, as an adjustment's are (counted minus held). The
    count is the decision, so the document asks for no approval of its own:
    a difference past the count's tolerance was accepted by the person
    allowed to accept it before anything got this far.
    """
    today = await core_api.organizations.today_async(db, org_id)
    type_config = await get_type_config(db, org_id, DocumentType.ADJUSTMENT.value)
    profile = await get_or_create_profile(db, org_id)
    now = datetime.now(UTC)
    doc = Document(
        organization_id=org_id,
        type=DocumentType.ADJUSTMENT.value,
        number=await generate_number(
            db,
            org_id,
            DocumentType.ADJUSTMENT.value,
            type_config.sequence_format if type_config else None,
            today,
        ),
        status=DocumentStatus.COMPLETED.value,
        target_location_id=location_id,
        scheduled_date=today,
        external_reference=reference,
        notes=notes,
        stock_already_applied=True,
        currency=await resolve_document_currency(db, org_id, profile),
        created_by=user_id,
        confirmed_by=user_id,
        confirmed_at=now,
        completed_by=user_id,
        completed_at=now,
    )
    db.add(doc)
    await db.flush()
    for number, difference in enumerate(differences, start=1):
        db.add(
            DocumentLine(
                document_id=doc.id,
                item_id=difference.item_id,
                product_template_id=difference.product_template_id,
                name=difference.name,
                quantity=difference.quantity_delta,
                expected_quantity=difference.quantity_delta,
                done_quantity=difference.quantity_delta,
                uom_id=difference.uom_id,
                batch_number=difference.batch_number,
                notes=difference.notes,
                line_number=number,
                target_location_id=difference.location_id or location_id,
            )
        )
    await db.flush()
    await db.refresh(doc, ['lines'])
    recompute_document_values(doc, executed=True)

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
            'new_status': doc.status,
            'lines': len(differences),
            'external_reference': reference,
        },
        reason='document_completed',
    )
    await emit_transactional_safe(
        db,
        DocumentEvent.COMPLETED,
        await build_document_event_payload(db, doc, org_id),
    )
    return doc
