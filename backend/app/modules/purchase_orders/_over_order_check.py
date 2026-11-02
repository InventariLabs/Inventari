"""A receipt naming an order line cannot take it past what was ordered.

The guard used to live in the endpoint that builds a receipt out of an
order, and ``source_po_line_id`` is a field the client fills in: a receipt
posted straight to the documents endpoint, naming any order line and any
quantity, went round it. The order then held ``quantity_received`` above
``quantity_ordered`` and completed itself on that figure.

So the rule is asked of the document, at the two moments its numbers become
real — when it is confirmed and when it is completed — whichever door it
came in by. It is this module's: the warehouse asks every module's pre-post
check, and ours answers for the orders. What was ordered is ours; the
document figures, the tolerance and the permission are the warehouse's, asked
through ``warehouse_api``. With this module off, nobody asks and a receipt
that names an order line is a receipt like any other.

Every figure is compared in the product's stock unit. The order may say
10000 g and the receipt 20 kg; compared as written, twenty is less than ten
thousand and twice the order walked in.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import DocumentToPostDTO
from app.core.public_api import core_api
from app.modules.warehouse.warehouse_api import OverReceiptRefusedError, warehouse_api

from .purchase_orders_api import purchase_orders_api

#: The name this module's check answers to.
MODULE = 'purchase_orders'


async def refuse_receipt_past_order_async(
    db: AsyncSession, org_id: UUID, document: DocumentToPostDTO
) -> None:
    """The pre-post check: refuse a document that overdraws an order line.

    *stage* picks which of the document's own figures counts: what it expects
    to bring while it is being confirmed, what it actually brought once it is
    being completed. Past what is left on the order line the over-receipt
    tolerance applies; past it the document needs the person carrying it out
    to hold ``warehouse:receive_over_tolerance``.
    """
    executed = document.stage == 'post'
    mine: dict[UUID, Decimal] = {}
    names: dict[UUID, str | None] = {}
    for line in document.lines:
        if line.source_po_line_id is None:
            continue
        names.setdefault(line.source_po_line_id, line.name)
        quantity = await core_api.uoms.to_stock_uom_async(
            db,
            org_id,
            line.product_template_id,
            (line.done_quantity if executed else line.expected_quantity)
            or Decimal('0'),
            line.uom_id,
        )
        mine[line.source_po_line_id] = (
            mine.get(line.source_po_line_id, Decimal('0')) + quantity
        )
    if not mine:
        return

    order_line_ids = list(mine)
    # An order line this organization does not have is one there is nothing
    # to check against.
    ordered = await purchase_orders_api.get_ordered_quantities_async(
        db, org_id, order_line_ids
    )
    if not ordered:
        return
    others = await warehouse_api.committed_to_order_lines_async(
        db, org_id, order_line_ids, excluding_document_id=document.id
    )
    labels = await purchase_orders_api.get_line_labels_async(db, org_id, order_line_ids)

    # Every surplus is gathered before anything is refused: a holder's yes
    # lifts the tolerance for the whole receipt, so the question has to
    # name each surplus that yes will let in, not only the first one met.
    refusals: list[str] = []
    questions: list[str] = []
    for order_line_id, quantity in mine.items():
        limit = ordered.get(order_line_id)
        if limit is None:
            continue
        remaining = limit - others.get(order_line_id, Decimal('0'))
        if quantity <= remaining:
            continue
        verdict = await warehouse_api.order_surplus_async(
            db,
            org_id,
            quantity=quantity,
            remaining=remaining,
            may_exceed=document.may_exceed_over_receipt,
            product=names.get(order_line_id),
            order_label=labels.get(order_line_id),
        )
        if verdict is not None:
            refusals.append(verdict[0])
            questions.append(verdict[1])
    if refusals:
        raise OverReceiptRefusedError(' '.join(refusals), question=' '.join(questions))
