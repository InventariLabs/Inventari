"""Posting and undoing a receipt does not send statements line by line.

A 200-line receipt went through the single-record door once per line, 64
statements a line, and the round trips — not the database — took twelve
seconds to post it and twenty-one to undo it. What can be written as a set is:
the movements, the cost layers, the history rows and the journal rows are
appended together, and what every line asks again (the organization, the unit,
the shelf) is asked once.

The shape is pinned on the statements the posting sends, not on a clock: how
many sets are written, and how the count grows with the lines. A posting that
went back to writing a row per line would grow by a statement per line per
table, and the bounds below would not hold.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.item_history import ItemHistory
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer

pytestmark = pytest.mark.integration

#: The tables a posting appends to. One statement each, however many lines.
_APPENDED = ('stock_moves', 'stock_valuation_layers', 'item_history', 'audit_log')

#: Lines of the two documents compared. Their difference is the growth.
_FEW, _MANY = 6, 18

#: Statements a posting may add per further line. Measured at six or seven,
#: leaving room for the next reference read that is not shared yet; the
#: statements this replaced were sixty-four a line.
_POST_PER_LINE = 9
_UNDO_PER_LINE = 1


@contextmanager
def _statements() -> Iterator[list[str]]:
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        text = re.sub(r'^/\*.*?\*/', '', ' '.join(statement.split()), flags=re.S)
        seen.append(text.strip().lower())

    event.listen(Engine, 'before_cursor_execute', record)
    try:
        yield seen
    finally:
        event.remove(Engine, 'before_cursor_execute', record)


def _inserts(seen: list[str], table: str) -> int:
    return sum(1 for s in seen if s.startswith(f'insert into {table} '))


def _confirmed_receipt(
    client: TestClient,
    headers: dict[str, str],
    header: dict[str, Any],
    templates: list[Any],
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            **header,
            'lines': [
                {
                    'product_template_id': str(t.id),
                    'expected_quantity': '3',
                    'unit_price': '2.50',
                }
                for t in templates
            ],
        },
    )
    assert created.status_code == 201, created.text
    doc_id: str = created.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    return doc_id


def _post_and_undo(
    client: TestClient,
    headers: dict[str, str],
    header: dict[str, Any],
    templates: list[Any],
) -> tuple[list[str], list[str]]:
    doc_id = _confirmed_receipt(client, headers, header, templates)
    with _statements() as posting:
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
    assert done.status_code == 200, done.text
    with _statements() as undoing:
        undone = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/undo', headers=headers
        )
    assert undone.status_code == 200, undone.text
    return posting, undoing


class TestAReceiptPostsItsLinesAsSets:
    def test_the_appended_rows_are_written_as_sets(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: Any,
    ) -> None:
        header = {
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
        }
        templates = [
            h.create_template(doc_org, name=f'Set product {n}') for n in range(_MANY)
        ]

        posting, undoing = _post_and_undo(client, doc_auth_headers, header, templates)

        for table in _APPENDED:
            assert _inserts(posting, table) <= 2, (table, 'post')
            assert _inserts(undoing, table) <= 4, (table, 'undo')

    def test_the_statements_do_not_grow_by_the_line_for_the_steps_that_are_sets(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: Any,
    ) -> None:
        header = {
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
        }
        few = [h.create_template(doc_org, name=f'Few {n}') for n in range(_FEW)]
        many = [h.create_template(doc_org, name=f'Many {n}') for n in range(_MANY)]

        post_few, undo_few = _post_and_undo(client, doc_auth_headers, header, few)
        post_many, undo_many = _post_and_undo(client, doc_auth_headers, header, many)

        growth = _MANY - _FEW
        assert (len(post_many) - len(post_few)) / growth <= _POST_PER_LINE
        assert (len(undo_many) - len(undo_few)) / growth <= _UNDO_PER_LINE

    def test_an_undo_locks_the_records_and_the_cost_layers_as_sets(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: Any,
    ) -> None:
        header = {
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
        }
        templates = [h.create_template(doc_org, name=f'Lock {n}') for n in range(_MANY)]

        _posting, undoing = _post_and_undo(client, doc_auth_headers, header, templates)

        # Taken for the undo's lines in one statement each, not one per line.
        records = [
            s for s in undoing if ' from items ' in s and ' for no key update' in s
        ]
        layers = [
            s
            for s in undoing
            if ' from stock_valuation_layers ' in s and ' for update' in s
        ]
        assert len(records) <= 2
        assert len(layers) <= 2

    def test_an_undo_asks_what_each_shelf_has_free_once_for_all_its_lines(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: Any,
    ) -> None:
        header = {
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
        }
        templates = [h.create_template(doc_org, name=f'Free {n}') for n in range(_MANY)]

        _posting, undoing = _post_and_undo(client, doc_auth_headers, header, templates)

        # The shelf-versus-reservations question, answered for every grain the
        # undo drew on in one statement, not asked again after each line.
        asked = [
            s
            for s in undoing
            if ' from items ' in s and ' sum(' in s and 'stock_reservations' in s
        ]
        assert len(asked) <= 1

    def test_what_was_written_is_what_a_line_by_line_posting_wrote(
        self,
        client: TestClient,
        db_session: Any,
        h: ModuleTestHelper,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: Any,
    ) -> None:
        header = {
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
        }
        templates = [h.create_template(doc_org, name=f'Kept {n}') for n in range(4)]
        doc_id = _confirmed_receipt(client, doc_auth_headers, header, templates)

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == 200, done.text

        moves = (
            db_session.execute(
                select(StockMove).where(StockMove.reference_id == UUID(doc_id))
            )
            .scalars()
            .all()
        )
        lines = {UUID(line['id']) for line in done.json()['lines']}
        layers = (
            db_session.execute(
                select(StockValuationLayer).where(
                    StockValuationLayer.document_line_id.in_(lines)
                )
            )
            .scalars()
            .all()
        )
        history = (
            db_session.execute(
                select(ItemHistory).where(
                    ItemHistory.source_document_id == UUID(doc_id)
                )
            )
            .scalars()
            .all()
        )
        journal = (
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.target_id == UUID(doc_id),
                    AuditLog.reason == 'document_completed',
                )
            )
            .scalars()
            .all()
        )

        assert len(moves) == len(layers) == len(history) == 4
        assert {m.product_template_id for m in moves} == {t.id for t in templates}
        assert all(m.to_location_id == doc_target_location.id for m in moves)
        assert all(m.quantity == Decimal('3') for m in moves)
        assert all(layer.quantity == Decimal('3') for layer in layers)
        assert all(layer.unit_cost == Decimal('2.5') for layer in layers)
        assert len(journal) == 1
