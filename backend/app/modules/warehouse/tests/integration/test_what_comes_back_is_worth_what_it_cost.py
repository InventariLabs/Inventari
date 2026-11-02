"""Goods that come back are worth what they cost, not what they sold for.

A customer's return and a dispatch corrected downwards both put goods back
on the shelf. The line they come back on carries the sales price -- it is
copied from the dispatch -- and the receipt layer used to be posted at it.
Every return then put the margin on the shelf: sold at 5.00 what cost 1.00,
taken back, and the books held 5.00 of stock where 1.00 had left.

The outflow they undo posted what the layers it consumed cost. The way
back in is priced off that figure, the mirror of a return to the supplier
being priced off the delivery it reverses.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis
from app.models.storage_location import StorageLocation

from .test_goods_go_back_the_way_they_came import (
    _correct,
    _layers,
    _receive,
    _return,
)

COST = '1.00'
SALES_PRICE = '5.00'


def _sell(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    location_id: UUID,
    template_id: UUID,
    db_session: Session,
    quantity: str,
) -> str:
    db_session.expire_all()
    item = db_session.scalars(
        select(Item).where(Item.template_id == template_id)
    ).first()
    assert item is not None
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(location_id),
            'lines': [
                {
                    'item_id': str(item.id),
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'unit_price': SALES_PRICE,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    assert (
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        ).status_code
        == status.HTTP_200_OK
    )
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


@pytest.fixture
def sale(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_partner: Partner,
    doc_template: ProductTemplate,
    db_session: Session,
) -> str:
    """Ten bought at 1.00, six of them sold at 5.00."""
    _receive(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        location_id=doc_source_location.id,
        template_id=doc_template.id,
        quantity='10',
        unit_price=COST,
    )
    return _sell(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        location_id=doc_source_location.id,
        template_id=doc_template.id,
        db_session=db_session,
        quantity='6',
    )


@pytest.mark.integration
class TestWhatComesBackIsWorthWhatItCost:
    def test_a_customer_return_comes_back_at_cost(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        db_session: Session,
        sale: str,
    ) -> None:
        code, body = _return(client, doc_auth_headers, document_id=sale, quantity='4')
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        bought, returned = _layers(db_session, doc_template.id, 'IN')
        assert bought.unit_cost == Decimal('1.0000')
        assert returned.unit_cost == Decimal('1.0000')
        assert returned.total_value == Decimal('4.00')
        assert returned.cost_basis == CostBasis.FIFO
        # The line itself still says what the customer paid: the document's
        # value is the refund, the layer's is the stock.
        assert returned.quantity == Decimal('4.000')

    def test_a_dispatch_corrected_downwards_comes_back_at_cost(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        db_session: Session,
        sale: str,
    ) -> None:
        code, body = _correct(client, doc_auth_headers, document_id=sale, delta='-4')
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        bought, restated = _layers(db_session, doc_template.id, 'IN')
        assert restated.unit_cost == Decimal('1.0000')
        assert restated.total_value == Decimal('4.00')
        assert restated.cost_basis == CostBasis.FIFO
        # What the books hold agrees with what the shelf holds: ten bought,
        # six gone, four back — 10.00 - 6.00 + 4.00 on layers worth 1.00 each.
        on_hand = sum(
            layer.remaining_qty * layer.unit_cost for layer in (bought, restated)
        )
        assert on_hand == Decimal('8.0000')

    def test_a_receipt_corrected_upwards_keeps_its_line_price(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The control: a line that posted no outflow is not a reversal."""
        receipt = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
            unit_price='3.00',
        )
        code, body = _correct(client, doc_auth_headers, document_id=receipt, delta='5')
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        delivered, more = _layers(db_session, doc_template.id, 'IN')
        assert more.unit_cost == Decimal('3.0000')
        assert more.total_value == Decimal('15.00')
        assert more.cost_basis == CostBasis.STATED
