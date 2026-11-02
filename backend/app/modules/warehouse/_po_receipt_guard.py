"""A document line naming an order line cannot take it past what was ordered.

``source_po_line_id`` is a field the client fills in, so the rule is asked of
the document, whichever door it came in by. At confirmation and completion it
is the orders module's own pre-post check (``purchase_orders``
``_over_order_check``); what that check needs of the warehouse — what the
other documents have already spoken for — is ``committed_by_others_async``
here, published through ``warehouse_api``. The doors that raise a single
line's quantity (the scan, the receiving session, a correction) ask the
question here, of the line, with the orders module consulted through
``order_side_async`` only while it is there.

Past what is left on the order line the over-receipt tolerance applies (see
``_over_receipt``): within it anyone may record the surplus, past it the
``warehouse:receive_over_tolerance`` permission is needed.

Every figure is compared in the product's stock unit. The order may say
10000 g and the receipt 20 kg; compared as written, twenty is less than ten
thousand and twice the order walked in.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._order_side import order_side_async
from .models import Document, DocumentLine, DocumentStatus


async def committed_by_others_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID | None,
    po_line_ids: list[UUID],
) -> dict[UUID, Decimal]:
    """``{po_line_id: quantity other documents have already spoken for}``.

    A completed receipt has brought what it says it brought; an open one has
    reserved what it expects. Cancelled documents reserve nothing, and the
    document being weighed — when there is one — is left out.
    """
    query = (
        select(
            DocumentLine.source_po_line_id,
            DocumentLine.done_quantity,
            DocumentLine.expected_quantity,
            DocumentLine.product_template_id,
            DocumentLine.uom_id,
            Document.status,
        )
        .join(Document, Document.id == DocumentLine.document_id)
        .where(
            DocumentLine.source_po_line_id.in_(po_line_ids),
            Document.organization_id == org_id,
            Document.status != DocumentStatus.CANCELLED.value,
        )
    )
    if doc_id is not None:
        query = query.where(Document.id != doc_id)
    result = await db.execute(query)
    totals: dict[UUID, Decimal] = {}
    for (
        po_line_id,
        done,
        expected,
        template_id,
        uom_id,
        doc_status,
    ) in result.all():
        if doc_status == DocumentStatus.COMPLETED.value:
            taken = done or Decimal('0')
        else:
            taken = max(expected or Decimal('0'), done or Decimal('0'))
        taken = await core_api.uoms.to_stock_uom_async(
            db, org_id, template_id, taken or Decimal('0'), uom_id
        )
        totals[po_line_id] = totals.get(po_line_id, Decimal('0')) + taken
    return totals


async def assert_line_over_receipt_allowed_async(
    db: AsyncSession,
    org_id: UUID,
    doc_line: DocumentLine | None,
    *,
    exclude_doc_id: UUID | None,
    quantity: Decimal,
    expected: Decimal,
    may_exceed: bool,
) -> None:
    """The ramp's question: may this line stand at *quantity*?

    An order-linked document line is measured against what is left on its
    order line, with the line's quantity converted to the order's stock
    unit. A line that names no order line is measured against its own
    expected quantity, in its own unit — unless that quantity is only a count
    somebody typed (``expected_is_count``), which leaves nothing to exceed. When the
    order module has nothing to say about the line, the expected figure is
    the fallback rather than a free pass.
    """
    from ._over_receipt import assert_over_receipt_allowed_async

    if doc_line is not None and doc_line.source_po_line_id is not None:
        remaining = await order_line_remaining_async(
            db, org_id, doc_line, exclude_doc_id=exclude_doc_id
        )
        if remaining is not None:
            quantity_stock = await core_api.uoms.to_stock_uom_async(
                db,
                org_id,
                doc_line.product_template_id,
                quantity,
                doc_line.uom_id,
            )
            await assert_over_receipt_allowed_async(
                db,
                org_id,
                quantity=quantity_stock,
                basis=remaining,
                may_exceed=may_exceed,
                product=doc_line.name,
                order_line_id=doc_line.source_po_line_id,
            )
            return
    if doc_line is not None and doc_line.expected_is_count:
        return
    await assert_over_receipt_allowed_async(
        db,
        org_id,
        quantity=quantity,
        basis=expected,
        may_exceed=may_exceed,
        product=doc_line.name if doc_line is not None else None,
    )


async def order_line_remaining_async(
    db: AsyncSession,
    org_id: UUID,
    doc_line: DocumentLine,
    *,
    exclude_doc_id: UUID | None,
) -> Decimal | None:
    """What is left on the order line *doc_line* names, in the stock unit.

    ``None`` when the line names no order line, or when the order module has
    nothing to say about it — the module is off, or the line is unknown —
    the same graceful degradation the guard above keeps. *exclude_doc_id* is
    the document being weighed against the order; it is left out of what
    other documents have already taken, so a session or a correction is not
    refused by its own expectation.
    """
    if doc_line.source_po_line_id is None:
        return None
    orders = await order_side_async(db, org_id)
    if orders is None:
        return None
    ordered = await orders.get_ordered_quantities_async(
        db, org_id, [doc_line.source_po_line_id]
    )
    limit = ordered.get(doc_line.source_po_line_id)
    if limit is None:
        return None
    others = await committed_by_others_async(
        db, org_id, exclude_doc_id, [doc_line.source_po_line_id]
    )
    return limit - others.get(doc_line.source_po_line_id, Decimal('0'))
