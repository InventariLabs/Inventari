from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from . import document_types as dt
from .document_numbering_service import temporary_number
from .document_value_service import recompute_document_values
from .models import BACKORDER_CODES, Document, DocumentLine, DocumentStatus

logger = get_logger(__name__)


async def maybe_create_backorder(
    db: AsyncSession,
    completed_doc: Document,
    org_id: UUID,
    user_id: UUID,
) -> Document | None:
    if not dt.is_backorder_eligible(completed_doc.type):
        return None

    shortage_lines = _find_shortage_lines(completed_doc)
    if not shortage_lines:
        return None

    backorder = await _create_backorder_document(
        db, completed_doc, shortage_lines, org_id, user_id
    )
    logger.info(
        'Created backorder %s for %s (%d lines)',
        backorder.number,
        completed_doc.number,
        len(shortage_lines),
    )
    return backorder


def _find_shortage_lines(doc: Document) -> list[DocumentLine]:
    # What the order is owed is the expected quantity minus what arrived as
    # usable stock. A held quantity arrived, but is not usable, so it is
    # outstanding like a shortage — and only it is: the rest of the line is
    # ordinary stock.
    #
    # The purchase order still owes the goods that did not arrive, but counts
    # held goods as delivered. Only the held part needs a separate replacement.
    result = []
    for line in doc.lines:
        held = line.held_quantity or Decimal('0')
        remaining = (
            held
            if line.source_po_line_id is not None
            else (line.expected_quantity - line.done_quantity + held)
        )
        if remaining > Decimal('0') and line.discrepancy_code in BACKORDER_CODES:
            result.append(line)
    return result


async def _create_backorder_document(
    db: AsyncSession,
    original: Document,
    shortage_lines: list[DocumentLine],
    org_id: UUID,
    user_id: UUID,
) -> Document:
    # The backorder is the same business paper as the receipt it came from,
    # so it is numbered by the receipt's own rule: a type with a numbering
    # format of its own numbers the backorder by that format too, which puts
    # the two pieces of one receipt's paper in one series. The number itself
    # is drawn when this draft is confirmed — the format read there is the
    # one this document's own type carries, which is the receipt's type.
    number = temporary_number()

    backorder = Document(
        organization_id=org_id,
        type=original.type,
        number=number,
        status=DocumentStatus.DRAFT.value,
        partner_id=original.partner_id,
        source_location_id=original.source_location_id,
        target_location_id=original.target_location_id,
        # No note: the backorder names the document it came from through
        # ``backorder_id``, and the screens read that link in the reader's
        # language. A stored English sentence ("Backorder for IN/…") reached
        # every language and printed.
        external_reference=original.external_reference,
        created_by=user_id,
        backorder_id=original.id,
        currency=original.currency,
        # The rest of the same paper: what a module required on it still holds.
        meta_data=original.meta_data,
    )

    for i, orig_line in enumerate(shortage_lines, 1):
        held = orig_line.held_quantity or Decimal('0')
        from_order = orig_line.source_po_line_id is not None
        remaining = (
            held
            if from_order
            else (orig_line.expected_quantity - orig_line.done_quantity + held)
        )
        new_line = DocumentLine(
            line_number=i,
            item_id=orig_line.item_id,
            product_template_id=orig_line.product_template_id,
            name=orig_line.name,
            brand=orig_line.brand,
            barcode=orig_line.barcode,
            quantity=remaining,
            expected_quantity=remaining,
            done_quantity=Decimal('0'),
            uom_id=orig_line.uom_id,
            batch_number=None if from_order else orig_line.batch_number,
            serial_number=None if from_order else orig_line.serial_number,
            expiry_date=None if from_order else orig_line.expiry_date,
            unit_price=orig_line.unit_price,
            tax_rate=orig_line.tax_rate,
            currency=orig_line.currency,
            source_po_line_id=None,
            meta_data=orig_line.meta_data,
        )
        backorder.lines.append(new_line)

    # The lines carry a price, so the document has a value — and it had none:
    # nothing computed one for a document the application creates itself, so
    # a backorder sat in the register priced and worth nothing, and a value
    # threshold on approvals read it as zero. It is a plan, so its value is
    # what it plans.
    recompute_document_values(backorder)

    db.add(backorder)
    await db.flush()
    return backorder
