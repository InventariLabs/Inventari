"""The demo documents have to move the stock their lines say they did.

A completed document on the demo is a claim: its execution summary reads
"Lines 2/2 done, Quantity 8/8". The register's "What this document moved"
read "This document moved nothing" — the seed wrote every document straight
to its final state (status, timestamps, done quantities) and never executed
its stock, so one screen said the goods had moved and the next said they had
not. The documents now run through the executor the application uses.

These tests hold the two halves together: every completed document's
movements net to what its done lines say, dated the day the document closed,
and a seed run that tops the volume up does not move them a second time.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.modules.warehouse.document_types import is_receipt, normalize
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus
from tests.integration._demo_world import ids, seeded_organization

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(demo_world) -> tuple[uuid.UUID, uuid.UUID]:
    """A demo organization seeded with every module."""
    payload = demo_world('org-60', seeded_organization(items=60))
    return ids(payload)


def _completed_documents(db: Session, org_id: uuid.UUID) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(
                Document.organization_id == org_id,
                Document.status == DocumentStatus.COMPLETED.value,
            )
            .order_by(Document.number)
        ).all()
    )


def _document_moves(
    db: Session, org_id: uuid.UUID, doc_id: uuid.UUID
) -> list[StockMove]:
    return list(
        db.scalars(
            select(StockMove).where(
                StockMove.organization_id == org_id,
                StockMove.reference_type == StockMoveReferenceType.DOCUMENT,
                StockMove.reference_id == doc_id,
            )
        ).all()
    )


def test_the_seed_wrote_completed_documents(db_session: Session, seeded) -> None:
    """Not a silence over nothing: the seed wrote documents to check."""
    org_id, _user_id = seeded

    assert _completed_documents(db_session, org_id), 'no completed documents to check'


def test_every_completed_document_has_movements_of_its_own(
    db_session: Session, seeded
) -> None:
    org_id, _user_id = seeded

    moved_nothing = [
        doc.number
        for doc in _completed_documents(db_session, org_id)
        if not _document_moves(db_session, org_id, doc.id)
    ]

    assert not moved_nothing, f'completed documents that moved nothing: {moved_nothing}'


def test_the_movements_net_to_what_the_done_lines_say(
    db_session: Session, seeded
) -> None:
    """A receipt's register sums to its done lines, a dispatch's to minus them."""
    org_id, _user_id = seeded

    for doc in _completed_documents(db_session, org_id):
        moves = _document_moves(db_session, org_id, doc.id)
        net = sum(
            (move.quantity if move.to_location_id else -move.quantity) for move in moves
        )
        done = db_session.scalar(
            select(func.coalesce(func.sum(DocumentLine.done_quantity), 0)).where(
                DocumentLine.document_id == doc.id
            )
        )
        expected = Decimal(done) if is_receipt(normalize(doc.type)) else -Decimal(done)
        assert net == expected, f'{doc.number}: moved {net}, lines say {expected}'


def test_the_movements_are_dated_when_the_document_closed(
    db_session: Session, seeded
) -> None:
    """A delivery's rows read the day it was put away, not the day of seeding."""
    org_id, _user_id = seeded

    for doc in _completed_documents(db_session, org_id):
        assert doc.completed_at is not None, f'{doc.number} has no completion date'
        moves = _document_moves(db_session, org_id, doc.id)
        assert moves, f'{doc.number} moved nothing — nothing dated was checked'
        wrong = [
            move.created_at
            for move in moves
            if move.created_at.date() != doc.completed_at.date()
        ]
        assert not wrong, f'{doc.number} moved on {wrong}, closed {doc.completed_at}'


def test_running_the_document_execution_again_moves_nothing(
    db_session: Session, seeded
) -> None:
    """The seed tops the volume up; a document's stock is not a second run's."""
    from seed_demo_data import _execute_the_seeded_documents

    org_id, user_id = seeded
    before = {
        doc.id: sum(
            move.quantity for move in _document_moves(db_session, org_id, doc.id)
        )
        for doc in _completed_documents(db_session, org_id)
    }

    assert _execute_the_seeded_documents(org_id, user_id) == 0

    after = {
        doc.id: sum(
            move.quantity for move in _document_moves(db_session, org_id, doc.id)
        )
        for doc in _completed_documents(db_session, org_id)
    }
    assert after == before


def test_the_completed_dispatch_names_the_stock_it_took(
    db_session: Session, seeded
) -> None:
    """A completed document's lines still have to name what they took."""
    org_id, _user_id = seeded
    dispatched = [
        doc
        for doc in _completed_documents(db_session, org_id)
        if not is_receipt(normalize(doc.type))
    ]
    assert dispatched, 'no completed dispatch to check'

    for doc in dispatched:
        unnamed = [line.line_number for line in doc.lines if line.item_id is None]
        assert not unnamed, f'{doc.number} took stock without a record: {unnamed}'
        named = {line.item_id for line in doc.lines}
        standing = set(
            db_session.scalars(select(Item.id).where(Item.id.in_(named))).all()
        )
        assert named <= standing, f'{doc.number} names records that do not exist'


def test_a_delivered_laptop_is_an_asset_from_the_day_it_arrives(
    db_session: Session, seeded
) -> None:
    """A receipt's equipment arrives with a status and a dated warranty.

    The test process has the interceptors wired by the application, so this
    holds the state the seed leaves behind (it passes with or without the
    wiring below); the next test holds the seeding process itself.
    """
    org_id, _user_id = seeded

    delivered = list(
        db_session.scalars(
            select(Item)
            .join(Category, Category.id == Item.category_id)
            .where(
                Item.organization_id == org_id,
                Category.context_tag == 'equipment',
                Item.id.in_(
                    select(ItemHistory.item_id).where(
                        ItemHistory.organization_id == org_id,
                        ItemHistory.source_document_id.is_not(None),
                    )
                ),
            )
        ).all()
    )

    assert delivered, 'no equipment delivered by a receipt — nothing was checked'
    unknown = [
        item.name
        for item in delivered
        if (item.meta_data.get('equipment') or {}).get('equipment_status') is None
    ]
    assert not unknown, f'delivered but listed as Unknown assets: {unknown}'
    undated = [
        item.name
        for item in delivered
        if not (item.meta_data['equipment'].get('warranty_until'))
    ]
    assert not undated, f'delivered without a warranty date: {undated}'


def test_the_seeding_process_wires_the_equipment_interceptor(monkeypatch) -> None:
    """A plain script has no startup, so its pipeline is empty.

    A receipt then opened an equipment-category record with no equipment
    namespace, listed as an Unknown asset with no serial or warranty. The
    seed has to wire the interceptor the server wires at startup.
    """
    from app.core.interceptors import interceptor_pipeline
    from app.modules.equipment.interceptors import EquipmentItemInterceptor
    from seed_demo_data import _wire_the_equipment_interceptor

    monkeypatch.setattr(interceptor_pipeline, '_item_interceptors', [])

    _wire_the_equipment_interceptor()

    assert any(
        isinstance(i, EquipmentItemInterceptor)
        for i in interceptor_pipeline._item_interceptors
    )
