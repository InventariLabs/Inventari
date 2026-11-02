"""The order list counts and sums the lines; it carries them only when asked.

A page of fifty orders carried every line of every order — 400 KB — while
the list prints a count and the receipt progress per unit. The row now
carries ``line_count`` and ``unit_progress`` and leaves ``lines`` empty.
The receive screen, choosing which open order's lines to receive, asks
``with_lines`` and gets them.

Leaving the lines out of the answer was not enough: the page still built
every line of fifty orders, with its product, to count them and drop them,
and every fourteenth request or so stalled for half a second at 100 000
products. The figures are summed in the database now, so the page reads
no line and no product at all.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine

pytestmark = pytest.mark.integration

URL = '/api/v1/purchase-orders'


@pytest.fixture
def order(
    db_session: Session,
    po_org: Any,
    po_user: Any,
    po_partner: Any,
    po_uom_pcs: Any,
    po_uom_kg: Any,
) -> PurchaseOrder:
    """Two units on one order: 24 + 6 pcs, half of them in; 10 kg, none.

    Priced two ways a total meets: a rate and no rate; the unpriced line's
    effect on the total has a test of its own.
    """
    po = PurchaseOrder(
        organization_id=po_org.id,
        number='PO-ROWS-1',
        status='CONFIRMED',
        partner_id=po_partner.id,
        created_by=po_user.id,
    )
    lines = [
        ('Bolts', po_uom_pcs, '24', '12', '1.25', '23'),
        ('Grease', po_uom_kg, '10', '0', '0', '8'),
        ('Nuts', po_uom_pcs, '6', '3', '0.40', None),
    ]
    db_session.add(po)
    for number, (name, uom, ordered, received, price, rate) in enumerate(
        lines, start=1
    ):
        db_session.add(
            PurchaseOrderLine(
                purchase_order=po,
                name=name,
                uom_id=uom.id,
                quantity_ordered=Decimal(ordered),
                quantity_received=Decimal(received),
                unit_price=None if price is None else Decimal(price),
                tax_rate=None if rate is None else Decimal(rate),
                line_number=number,
            )
        )
    db_session.commit()
    return po


def _only_row(client: TestClient, headers: dict[str, str], **params: Any) -> Any:
    response = client.get(URL, headers=headers, params=params)
    assert response.status_code == status.HTTP_200_OK, response.text
    (row,) = response.json()['items']
    return row


@pytest.mark.usefixtures('order')
class TestTheOrderList:
    def test_the_row_counts_and_sums_the_lines_it_leaves_out(
        self, client: TestClient, po_auth_headers: dict[str, str]
    ) -> None:
        row = _only_row(client, po_auth_headers)

        assert row['lines'] == []
        assert row['line_count'] == 3
        assert [
            (g['unit'], Decimal(g['ordered']), Decimal(g['received']))
            for g in row['unit_progress']
        ] == [('pcs', Decimal('30'), Decimal('15')), ('kg', Decimal('10'), 0)]

    def test_the_receive_screen_asks_for_the_lines(
        self, client: TestClient, po_auth_headers: dict[str, str]
    ) -> None:
        row = _only_row(client, po_auth_headers, with_lines=True)

        assert [line['name'] for line in row['lines']] == ['Bolts', 'Grease', 'Nuts']
        assert row['line_count'] == 3

    def test_the_row_totals_the_order_as_its_card_does(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        order: PurchaseOrder,
    ) -> None:
        row = _only_row(client, po_auth_headers)
        card = client.get(f'{URL}/{order.id}', headers=po_auth_headers).json()

        # The strings, not the values: the same scale as the card prints.
        assert [row[f] for f in ('total_net', 'total_tax', 'total_gross')] == [
            card[f] for f in ('total_net', 'total_tax', 'total_gross')
        ]
        assert Decimal(row['total_gross']) == Decimal('39.30')

    def test_the_page_reads_no_line_and_no_product(
        self, client: TestClient, po_auth_headers: dict[str, str]
    ) -> None:
        statements: list[str] = []

        def _record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            statements.append(statement)

        # The request runs on the app's engine; the listener sits on the class.
        event.listen(Engine, 'before_cursor_execute', _record)
        try:
            _only_row(client, po_auth_headers)
        finally:
            event.remove(Engine, 'before_cursor_execute', _record)

        line_reads = [s for s in statements if 'purchase_order_lines' in s]
        assert line_reads
        assert all('GROUP BY' in s for s in line_reads), line_reads
        assert not [s for s in statements if 'product_templates' in s]
