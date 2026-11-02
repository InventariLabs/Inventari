"""Stock executor dispatcher — routes document lines to operation handlers.

The handlers live in sibling modules to keep this file focused on dispatch:
  - _stock_executor_receipt: IN receipts
  - _stock_executor_outbound: OUT dispatch + scrap
  - _stock_executor_transfer: MM transfers
  - _stock_executor_deltas: corrections + adjustments

execute_stock_operations is the single public entry point.
_execute_correction is re-exported for the unit-test mocks.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from . import document_types as dt
from ._receipt_planning import ReceiptLocationPlanner
from ._stock_executor_deltas import (
    execute_adjustment as _execute_adjustment,
)
from ._stock_executor_deltas import (
    execute_correction as _execute_correction,
)
from ._stock_executor_helpers import _executed_quantity, lock_document_stock_async
from ._stock_executor_outbound import dispatch_item as _dispatch_item
from ._stock_executor_outbound import scrap_item as _scrap_item
from ._stock_executor_receipt import _receive_item
from ._stock_executor_transfer import transfer_item as _transfer_item
from .extra_costs_service import surcharges_async
from .models import Document


async def execute_stock_operations(
    db: AsyncSession,
    doc: Document,
    user_id: UUID,
    *,
    unit_confirmed_over_template: bool = False,
) -> None:
    """Run the document's lines through the doors that move the stock.

    *unit_confirmed_over_template* is the operator's answer from the
    execution screen, riding the completion payload: a record whose unit
    differs from the card it is being adopted into stops each door unless
    the difference was confirmed. It is a completion-level answer — it
    speaks for every line of the document, the way the dialog that produced
    it does.
    """
    # The shelves already moved for this document (a picking session took the
    # ingredients as they were picked); the document is the register's copy.
    if doc.stock_already_applied:
        return
    async with core_api.stock.posting_scope_async(db):
        await _execute_the_lines(
            db,
            doc,
            user_id,
            unit_confirmed_over_template=unit_confirmed_over_template,
        )


async def _execute_the_lines(
    db: AsyncSession,
    doc: Document,
    user_id: UUID,
    *,
    unit_confirmed_over_template: bool,
) -> None:
    # Before the first line: the lines lock nothing one by one that the
    # document does not already hold (see ``lock_document_stock_async``).
    await lock_document_stock_async(db, doc)
    # The products of all the lines are read together and kept, so each line's
    # lookup of its own product finds it without a query.
    await core_api.product_templates.get_many_async(
        db,
        doc.organization_id,
        list(
            {line.product_template_id for line in doc.lines if line.product_template_id}
        ),
    )
    # A signed-delta pass asks each grain it moved stock off whether its
    # reservations are still covered once, when the last line is written.
    if dt.is_correction(doc.type):
        async with core_api.stock.ask_what_each_grain_has_free_once_async(
            db, doc.organization_id
        ):
            await _execute_correction(
                db,
                doc,
                user_id,
                unit_confirmed_over_template=unit_confirmed_over_template,
            )
        return

    if dt.is_adjustment(doc.type):
        async with core_api.stock.ask_what_each_grain_has_free_once_async(
            db, doc.organization_id
        ):
            await _execute_adjustment(
                db,
                doc,
                user_id,
                unit_confirmed_over_template=unit_confirmed_over_template,
            )
        return

    # Freight, duty and insurance are spread once, over the whole delivery,
    # before the first line is posted: a share can only be worked out when
    # every line is known, and the layers are written line by line.
    # The putaway planner loads the organization's rules once for the same
    # reason — every receipt line asks it where the goods belong.
    surcharges: dict[UUID, Decimal] = {}
    planner: ReceiptLocationPlanner | None = None
    if dt.is_receipt(doc.type):
        surcharges, _fallbacks = await surcharges_async(db, doc)
        planner = await ReceiptLocationPlanner.for_document(db, doc, user_id=user_id)

    # A snapshot: a dispatch line that took goods of several dates is split
    # into one line per date while it is posted, and the new lines are
    # already posted.
    for line in list(doc.lines):
        if _executed_quantity(line) <= 0:
            continue
        if dt.is_receipt(doc.type):
            assert planner is not None  # receipt docs always build one above
            await _receive_item(
                db,
                doc,
                line,
                user_id,
                surcharges.get(line.id, Decimal('0')),
                planner=planner,
                unit_confirmed_over_template=unit_confirmed_over_template,
            )
        elif dt.is_scrap(doc.type):
            await _scrap_item(
                db,
                doc,
                line,
                user_id,
                unit_confirmed_over_template=unit_confirmed_over_template,
            )
        elif dt.is_dispatch(doc.type):
            await _dispatch_item(
                db,
                doc,
                line,
                user_id,
                unit_confirmed_over_template=unit_confirmed_over_template,
            )
        elif dt.is_transfer(doc.type):
            await _transfer_item(
                db,
                doc,
                line,
                user_id,
                unit_confirmed_over_template=unit_confirmed_over_template,
            )
