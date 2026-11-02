"""One document can carry two tasks in To do; each needs a key of its own."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from app.modules.warehouse.models import Document
from app.modules.warehouse.work_item_service import _document_item


def _document() -> Document:
    doc = Document(
        id=uuid4(),
        number='WZ/1',
        type='WZ',
        status='CONFIRMED',
        lines=[],
    )
    doc.created_at = datetime(2026, 10, 20, tzinfo=UTC)
    return doc


def test_the_ship_and_approve_tasks_of_one_document_do_not_share_a_key() -> None:
    doc = _document()
    today = date(2026, 10, 20)

    ship = _document_item(doc, kind='ship', date_to=today)
    approve = _document_item(
        doc, kind='approve', date_to=today, next_action='review_approval'
    )

    assert ship.key != approve.key
    assert ship.source_id == approve.source_id
