"""Lines answer in line_number order, not in the heap's.

The ``lines`` relationship carried no ``order_by``, so Postgres handed the
rows back in heap order -- under load and parallel workers that is not the
insertion order, and the order, its PDF and its receipt presented positions
the caller never entered in that sequence (the flake in
``test_a_line_with_a_template_names_the_product`` unpacked a swapped pair).

The insertion here is deliberately reversed: line_number 2 enters the heap
before line_number 1, so a load without an ORDER BY fails exactly the way
the flake did -- the physical order opposes the logical one, and only the
relationship's own ORDER BY can undo it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine

pytestmark = pytest.mark.integration


def _line(po: PurchaseOrder, number: int, name: str) -> PurchaseOrderLine:
    return PurchaseOrderLine(
        purchase_order=po,
        name=name,
        quantity_ordered=Decimal('1'),
        quantity_received=Decimal('0'),
        line_number=number,
    )


def test_lines_answer_in_line_number_order(
    db_session: Session, po_org: Any, po_user: Any, po_partner: Any
) -> None:
    po = PurchaseOrder(
        organization_id=po_org.id,
        number='PO-LINE-ORDER-1',
        partner_id=po_partner.id,
        created_by=po_user.id,
    )
    # Reversed physical insertion: the heap keeps line_number 2 in front.
    second = _line(po, 2, 'Entered second, numbered first')
    first = _line(po, 1, 'Entered first, numbered second')
    db_session.add_all([po, second, first])
    db_session.commit()

    numbers = [line.line_number for line in po.lines]
    assert numbers == [1, 2]
    assert [line.name for line in po.lines] == [
        'Entered first, numbered second',
        'Entered second, numbered first',
    ]


def test_the_api_answers_with_the_lines_in_line_number_order(
    client: TestClient,
    db_session: Session,
    po_auth_headers: dict[str, str],
    po_org: Any,
    po_user: Any,
    po_partner: Any,
) -> None:
    po = PurchaseOrder(
        organization_id=po_org.id,
        number='PO-LINE-ORDER-2',
        partner_id=po_partner.id,
        created_by=po_user.id,
    )
    db_session.add_all(
        [po, _line(po, 3, 'Three'), _line(po, 1, 'One'), _line(po, 2, 'Two')]
    )
    db_session.commit()

    fetched = client.get(
        f'/api/v1/purchase-orders/{po.id}',
        headers=po_auth_headers,
    )
    assert fetched.status_code == status.HTTP_200_OK, fetched.text
    assert [line['line_number'] for line in fetched.json()['lines']] == [1, 2, 3]
    assert [line['name'] for line in fetched.json()['lines']] == ['One', 'Two', 'Three']
