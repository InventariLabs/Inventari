"""An order line or a receipt line takes only a price a record can keep.

A line's price becomes the purchase price of the record the delivery opens, and
that column holds from nothing up to ``PRICE_MAX``. Every door that writes a
line refuses a price outside that range there and then; a price that already
stands is carried into a copy as it is.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from fastapi import status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.contracts import PurchaseOrderLineInput
from app.modules.purchase_orders.models import PurchaseOrderLine
from app.modules.warehouse.models import Document, DocumentLine

pytestmark = pytest.mark.integration

ORDERS_URL = '/api/v1/purchase-orders'
DOCUMENTS_URL = '/api/v1/warehouse/documents'
TOO_BIG_OR_NEGATIVE = ['1000000000', '100000000', '-1']


def _receipt(location_id: Any, template_id: Any, price: str) -> dict[str, Any]:
    return {
        'type': 'PW',
        'target_location_id': str(location_id),
        'lines': [
            {
                'product_template_id': str(template_id),
                'expected_quantity': '1',
                'unit_price': price,
            }
        ],
    }


def _order(template_id: Any, price: str) -> dict[str, Any]:
    return {
        'lines': [
            {
                'product_template_id': str(template_id),
                'quantity_ordered': '1',
                'unit_price': price,
            }
        ]
    }


def _names_the_price(response: Any) -> bool:
    return any('unit_price' in error['loc'] for error in response.json()['detail'])


@pytest.mark.parametrize('price', TOO_BIG_OR_NEGATIVE)
def test_a_document_line_price_out_of_range_is_not_written(
    price: str,
    client: TestClient,
    po_auth_headers: dict[str, str],
    db_session: Session,
    po_location: Any,
    po_template: Any,
) -> None:
    response = client.post(
        DOCUMENTS_URL,
        headers=po_auth_headers,
        json=_receipt(po_location.id, po_template.id, price),
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, response.text
    assert _names_the_price(response), response.text
    assert db_session.scalars(select(Document)).first() is None


@pytest.mark.parametrize('price', ['0', '99999999.99'])
def test_the_ends_of_the_range_are_received(
    price: str,
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_location: Any,
    po_template: Any,
) -> None:
    created = client.post(
        DOCUMENTS_URL,
        headers=po_auth_headers,
        json=_receipt(po_location.id, po_template.id, price),
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_url = f'{DOCUMENTS_URL}/{created.json()["id"]}'
    confirmed = client.patch(f'{doc_url}/confirm', headers=po_auth_headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    completed = client.patch(
        f'{doc_url}/complete',
        headers=po_auth_headers,
        json={'complete_as_planned': True},
    )

    assert completed.status_code == status.HTTP_200_OK, completed.text


@pytest.mark.parametrize('price', TOO_BIG_OR_NEGATIVE)
def test_an_order_line_price_out_of_range_is_not_written(
    price: str,
    client: TestClient,
    po_auth_headers: dict[str, str],
    db_session: Session,
    po_template: Any,
) -> None:
    response = client.post(
        ORDERS_URL, headers=po_auth_headers, json=_order(po_template.id, price)
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, response.text
    assert _names_the_price(response), response.text
    assert db_session.scalars(select(PurchaseOrderLine)).first() is None


@pytest.mark.parametrize('price', TOO_BIG_OR_NEGATIVE)
def test_another_modules_order_line_is_held_to_the_same_range(price: str) -> None:
    with pytest.raises(ValidationError, match='unit_price'):
        PurchaseOrderLineInput(
            name='Anything', quantity_ordered=Decimal('1'), unit_price=Decimal(price)
        )


@pytest.mark.parametrize('price', ['1000000000', '-1'])
def test_an_order_import_names_the_price_cell(
    price: str,
    client: TestClient,
    po_auth_headers: dict[str, str],
    db_session: Session,
    po_template: Any,
) -> None:
    created = client.post(
        ORDERS_URL, headers=po_auth_headers, json=_order(po_template.id, '2.00')
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    sheet = pd.DataFrame([{'name': 'Sheet line', 'quantity': 1, 'unit_price': price}])

    response = client.post(
        f'{ORDERS_URL}/{created.json()["id"]}/import-lines',
        headers=po_auth_headers,
        files={'file': ('order.csv', sheet.to_csv(index=False), 'text/csv')},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert response.json()['imported'] == 0, response.text
    assert response.json()['errors'][0]['code'] == 'IMPORT_PRICE_INVALID'
    assert len(db_session.scalars(select(PurchaseOrderLine)).all()) == 1


@pytest.mark.parametrize('price', ['1000000000', '-1'])
def test_a_document_import_names_the_price_cell(
    price: str,
    client: TestClient,
    po_auth_headers: dict[str, str],
    db_session: Session,
    po_location: Any,
    po_template: Any,
) -> None:
    created = client.post(
        DOCUMENTS_URL,
        headers=po_auth_headers,
        json=_receipt(po_location.id, po_template.id, '2.00'),
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text

    response = client.post(
        f'{DOCUMENTS_URL}/{created.json()["id"]}/import-paste',
        headers=po_auth_headers,
        json={
            'text': f'name\tquantity\tprice\nTest Product\t1\t{price}\n',
            'mapping_json': {
                'name': 'name',
                'quantity': 'quantity',
                'unit_price': 'price',
            },
        },
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert response.json()['errors'][0]['code'] == 'IMPORT_PRICE_INVALID'
    assert len(db_session.scalars(select(DocumentLine)).all()) == 1


def test_a_stored_negative_price_is_carried_into_a_receipt_and_a_copy(
    client: TestClient,
    po_auth_headers: dict[str, str],
    db_session: Session,
    po_location: Any,
    po_template: Any,
    po_partner: Any,
) -> None:
    """The bounds are for what a request names, not for a row copied onward."""
    created = client.post(
        ORDERS_URL,
        headers=po_auth_headers,
        json={
            'partner_id': str(po_partner.id),
            **_order(po_template.id, '2.00'),
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_url = f'{ORDERS_URL}/{created.json()["id"]}'
    confirmed = client.post(f'{po_url}/confirm', headers=po_auth_headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    line = db_session.scalars(select(PurchaseOrderLine)).one()
    line.unit_price = Decimal('-1.00')
    db_session.commit()

    receipt = client.post(
        f'{po_url}/create-receipt',
        headers=po_auth_headers,
        json={'target_location_id': str(po_location.id)},
    )

    assert receipt.status_code == status.HTTP_201_CREATED, receipt.text
    assert Decimal(str(receipt.json()['lines'][0]['unit_price'])) == Decimal('-1')

    copy = client.post(
        f'{DOCUMENTS_URL}/{receipt.json()["id"]}/duplicate', headers=po_auth_headers
    )

    assert copy.status_code == status.HTTP_201_CREATED, copy.text
    assert Decimal(str(copy.json()['lines'][0]['unit_price'])) == Decimal('-1')
