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

from . import document_types as dt
from ._line_reversals import reversible_quantity_async
from .document_numbering_service import temporary_number
from .document_query_service import get_document
from .models import Document, DocumentLine, DocumentRelation, DocumentStatus

logger = get_logger(__name__)


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
            raise ServiceRejectionError(
                'document_return_quantity_exceeds_left',
                quantity=return_qty,
                line=orig_line_num,
                left=left,
                done=orig_line.done_quantity,
            )

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
