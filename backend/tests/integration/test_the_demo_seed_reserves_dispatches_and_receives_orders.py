"""Two accounts the demo seed used to write without the thing behind them.

A confirmed dispatch holds the stock it will take: Confirm reserves it, and
the stock screen reads "Available" as what is on hand minus those holds. The
seed wrote its dispatches already confirmed and held nothing, so Available
equalled On hand for goods two open dispatches were about to take.

An order line's received quantity is recounted from the completed receipts
that name it each time one completes. The seed wrote "3 received" on the
half delivered order with no receipt, so the first real receipt turned the
3 of 5 into whatever it brought.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock_move import StockMove, StockMoveReferenceType
from app.models.stock_reservation import StockReservation
from app.modules.purchase_orders.models import PurchaseOrderLine
from app.modules.warehouse.models import Document, DocumentLine
from app.modules.warehouse.warehouse_api import warehouse_api
from tests.integration._demo_world import ids, seeded_organization
from tests.integration._shelf import run_in_async_session

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(demo_world) -> uuid.UUID:
    payload = demo_world('org-60', seeded_organization(items=60))
    return ids(payload)[0]


def test_every_confirmed_dispatch_holds_what_its_lines_take(
    db_session: Session, seeded: uuid.UUID
) -> None:
    confirmed = (
        db_session.query(Document)
        .filter(
            Document.organization_id == seeded,
            Document.type == 'OUT',
            Document.status == 'CONFIRMED',
        )
        .all()
    )
    assert confirmed, 'the demo should leave dispatches for a visitor to pick'
    for doc in confirmed:
        taken = sum(line.quantity for line in doc.lines)
        held = (
            db_session.query(func.coalesce(func.sum(StockReservation.quantity), 0))
            .filter(StockReservation.document_id == doc.id)
            .scalar()
        )
        assert held == taken, f'{doc.number} takes {taken} but holds {held}'


def test_a_dispatch_the_walk_completed_holds_nothing_any_more(
    db_session: Session, seeded: uuid.UUID
) -> None:
    held_by_finished = (
        db_session.query(StockReservation.id)
        .join(Document, Document.id == StockReservation.document_id)
        .filter(
            StockReservation.organization_id == seeded,
            Document.status == 'COMPLETED',
        )
        .count()
    )
    assert held_by_finished == 0


def test_the_part_delivered_order_counts_a_receipt_the_seed_wrote(
    db_session: Session, seeded: uuid.UUID, async_engine_fixture
) -> None:
    line = (
        db_session.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.quantity_received > 0)
        .join(
            Document,
            Document.organization_id == seeded,
        )
        .join(DocumentLine, DocumentLine.source_po_line_id == PurchaseOrderLine.id)
        .filter(DocumentLine.document_id == Document.id)
        .one()
    )
    assert line.quantity_received == Decimal('3')

    async def _recount(session):
        return await warehouse_api.get_active_received_quantities_async(
            session, seeded, [line.id]
        )

    recount = run_in_async_session(async_engine_fixture, _recount)
    assert recount == {line.id: Decimal('3')}

    receipt = (
        db_session.query(Document)
        .join(DocumentLine, DocumentLine.document_id == Document.id)
        .filter(DocumentLine.source_po_line_id == line.id)
        .one()
    )
    assert receipt.status == 'COMPLETED'
    moved = (
        db_session.query(StockMove)
        .filter(
            StockMove.organization_id == seeded,
            StockMove.reference_type == StockMoveReferenceType.DOCUMENT,
            StockMove.reference_id == receipt.id,
        )
        .count()
    )
    assert moved, 'the receipt says it brought goods but moved no stock'
