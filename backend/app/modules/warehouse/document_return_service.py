from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.i18n.service import get_unit_label, stated_quantity

from . import document_types as dt
from ._line_reversals import reversible_quantities_async, reversible_quantity_async
from .document_numbering_service import temporary_number
from .document_query_service import get_document
from .models import Document, DocumentLine, DocumentRelation, DocumentStatus

logger = get_logger(__name__)


async def _beyond_left(
    db: AsyncSession,
    org_id: UUID,
    original_line: DocumentLine,
    quantity: Decimal,
    left: Decimal,
) -> ServiceRejectionError:
    """The refusal of a return taking *quantity* of a line that has *left* to give."""
    unit = ''
    if original_line.uom_id is not None:
        uom = await core_api.uoms.get_async(db, original_line.uom_id, org_id)
        unit = f' {get_unit_label(uom.symbol)}' if uom else ''
    return ServiceRejectionError(
        'document_return_quantity_exceeds_left',
        quantity=f'{stated_quantity(quantity)}{unit}',
        line=original_line.line_number,
        left=f'{stated_quantity(left)}{unit}',
        done=f'{stated_quantity(original_line.done_quantity)}{unit}',
    )


async def create_return(
    db: AsyncSession,
    original_id: UUID,
    lines: list[dict[str, Any]],
    org_id: UUID,
    user_id: UUID,
    notes: str | None = None,
    reason_code: str | None = None,
) -> Document:
    # Serialise returns against the same original: two concurrent returns
    # would each read "still there" before either wrote, and both pass the
    # bound. Same shape as the correction service.
    await acquire_advisory_lock(db, f'document_return:{original_id}')
    original = await get_document(db, org_id, original_id)
    if not original:
        raise ServiceRejectionError('document_not_found')

    if original.status != DocumentStatus.COMPLETED.value:
        raise ServiceRejectionError('document_return_requires_completed')

    if not dt.is_return_eligible(original.type):
        raise ServiceRejectionError('document_return_type_not_eligible')

    if not lines:
        raise ServiceRejectionError('document_return_no_lines')

    orig_line_map: dict[int, DocumentLine] = {
        line.line_number: line for line in original.lines
    }

    doc_return_type = dt.return_type(original.type)
    # A return is a draft like any other: it carries an identifier until
    # confirmation draws its number (see document_numbering_service).
    number = temporary_number()

    # The goods go back the way they came, so the places swap: a receipt's
    # return leaves from where the goods landed, a transfer's goes back to
    # where it started, and a delivery's return - a receipt - comes in to
    # the shelf the delivery took them from. A receipt's place is its
    # target; left in the source field, the receipt's planning never read it.
    source_loc = original.target_location_id
    target_loc = original.source_location_id

    return_doc = Document(
        organization_id=org_id,
        type=doc_return_type,
        number=number,
        status=DocumentStatus.DRAFT.value,
        partner_id=original.partner_id,
        source_location_id=source_loc,
        target_location_id=target_loc,
        notes=notes,
        reason_code=reason_code,
        # Other modules' fields go back with the goods, as on a correction.
        meta_data=original.meta_data,
        created_by=user_id,
        currency=original.currency,
    )

    for i, return_line in enumerate(lines, 1):
        orig_line_num = return_line['original_line_number']
        return_qty = Decimal(str(return_line['return_quantity']))
        reason = return_line.get('reason')

        if orig_line_num not in orig_line_map:
            raise ServiceRejectionError(
                'document_original_line_missing',
                line=orig_line_num,
                number=original.number,
            )

        orig_line = orig_line_map[orig_line_num]

        if return_qty <= Decimal('0'):
            raise ServiceRejectionError(
                'document_return_quantity_not_positive', line=orig_line_num
            )

        # The unit's own step, as the document form's own door asks it: a
        # return of 1.5 of something counted in pieces is half a piece
        # leaving the shelf. This path builds its lines by hand, so the
        # question has to be asked here too.
        if orig_line.uom_id is not None:
            await core_api.uoms.validate_quantity_precision_async(
                db, orig_line.uom_id, return_qty, org_id
            )

        # What is still there, not what once arrived: a line already
        # returned in full, or corrected away, has nothing left to send back.
        left = await reversible_quantity_async(db, org_id, orig_line)
        if return_qty > left:
            raise await _beyond_left(db, org_id, orig_line, return_qty, left)

        new_line = DocumentLine(
            line_number=i,
            item_id=orig_line.item_id,
            product_template_id=orig_line.product_template_id,
            name=orig_line.name,
            brand=orig_line.brand,
            barcode=orig_line.barcode,
            quantity=return_qty,
            expected_quantity=return_qty,
            done_quantity=Decimal('0'),
            uom_id=orig_line.uom_id,
            batch_number=orig_line.batch_number,
            serial_number=orig_line.serial_number,
            expiry_date=orig_line.expiry_date,
            unit_price=orig_line.unit_price,
            tax_rate=orig_line.tax_rate,
            corrects_line_id=orig_line.id,
            currency=orig_line.currency,
            notes=reason,
            meta_data=orig_line.meta_data,
        )
        return_doc.lines.append(new_line)

    db.add(return_doc)
    await db.flush()

    # The pointer to the receipt/transfer this return reverses. Screens and
    # the printout name the original from it, in the reader's own language —
    # which is why the return stores no note sentence: one written here is
    # stored once and then reaches every reader, whatever language each of
    # them reads in.
    relation = DocumentRelation(
        source_document_id=original.id,
        target_document_id=return_doc.id,
        relation_type='returns',
    )
    db.add(relation)

    # The return names the delivery it reverses, so the log answers "who sent
    # the goods back" without joining anything.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=return_doc.id,
        snapshot={
            'number': return_doc.number,
            'type': return_doc.type,
            'original_number': original.number,
            'reason_code': reason_code,
        },
    )

    await db.flush()
    # Read the return back the way a GET would, not by refreshing the object
    # we just built. Its lines sit in the identity map with their unit never
    # loaded, and touching ``line.uom`` lazily inside an async session is an
    # error, not a query — the response crashed on the way out, after the
    # return had already been written. (Same shape as the correction service.)
    return_doc = (
        (
            await db.execute(
                select(Document)
                .options(selectinload(Document.lines))
                .where(Document.id == return_doc.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .one()
    )
    # The response is a read of the return, so it carries the same pointer
    # the read path attaches: the screens name the original from it, in the
    # reader's language.
    return_doc.return_of_id = original.id  # type: ignore[attr-defined]
    return_doc.return_of_number = original.number  # type: ignore[attr-defined]

    logger.info(
        'Created return %s (type=%s) for %s (%d lines)',
        return_doc.number,
        doc_return_type,
        original.number,
        len(lines),
    )
    return return_doc


def _goods(line: DocumentLine) -> tuple[object, ...]:
    """What a return line gives back, as the edit form sends it again."""
    return (
        line.item_id,
        line.product_template_id,
        line.batch_number,
        line.serial_number,
    )


def return_links(
    lines: Sequence[DocumentLine],
) -> list[tuple[tuple[object, ...], UUID]]:
    """The original line each line of a return gives back, read before the lines are rewritten.

    The edit form sends a draft's lines back whole, and the document writes
    them anew; the link to the line a return gives back is not on the wire,
    so a return saved from the form stopped counting against its original.
    """
    return [
        (_goods(line), line.corrects_line_id)
        for line in sorted(lines, key=lambda line: line.line_number)
        if line.corrects_line_id is not None
    ]


def relink_return_lines(
    links: list[tuple[tuple[object, ...], UUID]], lines: Sequence[DocumentLine]
) -> None:
    """Give each rewritten line the link of the old line that carried the same goods.

    A line whose goods no old line carried stays without one, as a line
    added to a return always has.
    """
    free = list(links)
    for line in lines:
        match = next(
            (i for i, (goods, _) in enumerate(free) if goods == _goods(line)), None
        )
        if match is not None:
            line.corrects_line_id = free.pop(match)[1]


async def keep_return_within_left_async(
    db: AsyncSession, org_id: UUID, return_doc: Document
) -> None:
    """Refuse a return draft whose lines give back more than their original has left.

    ``create_return`` asks this line by line before it writes. A return also
    comes about as a copy of another one, and changes in the edit form; both
    are asked here, after the draft's lines are flushed, so the remainder
    counts them as it counts every return not cancelled. Behind the same lock
    as ``create_return``, so two of them cannot each read "still there".
    """
    taken: dict[UUID, Decimal] = {}
    for line in return_doc.lines:
        if line.corrects_line_id is not None:
            taken[line.corrects_line_id] = (
                taken.get(line.corrects_line_id, Decimal('0')) + line.quantity
            )
    if not taken:
        return
    originals = (
        (
            await db.execute(
                select(DocumentLine)
                .join(Document, Document.id == DocumentLine.document_id)
                .where(
                    DocumentLine.id.in_(taken),
                    Document.organization_id == org_id,
                )
                .order_by(DocumentLine.line_number)
            )
        )
        .scalars()
        .all()
    )
    if not originals:
        return
    await acquire_advisory_lock(db, f'document_return:{originals[0].document_id}')
    left = await reversible_quantities_async(db, org_id, originals)
    for original in originals:
        if left[original.id] < 0:
            raise await _beyond_left(
                db,
                org_id,
                original,
                taken[original.id],
                left[original.id] + taken[original.id],
            )


async def keep_the_copy_a_return_async(
    db: AsyncSession, org_id: UUID, copy: Document, source: Document
) -> None:
    """Make *copy* a return of the document *source* returns, line for line.

    A copy written as an ordinary document named no receipt and took nothing
    from what was left to return, so returns could add up past what the
    receipt brought in. It names the same original, its lines give back the
    lines the source's did, and it is refused when those have too little left.
    A *source* that returns nothing is left alone.
    """
    returned_id = getattr(source, 'return_of_id', None)
    if returned_id is None:
        return
    for copied, line in zip(copy.lines, source.lines, strict=True):
        copied.corrects_line_id = line.corrects_line_id
    db.add(
        DocumentRelation(
            source_document_id=returned_id,
            target_document_id=copy.id,
            relation_type='returns',
        )
    )
    await db.flush()
    await keep_return_within_left_async(db, org_id, copy)
    # The answer is a read of the copy, so it carries the pointer a GET does.
    copy.return_of_id = returned_id  # type: ignore[attr-defined]
    copy.return_of_number = getattr(source, 'return_of_number', None)  # type: ignore[attr-defined]
