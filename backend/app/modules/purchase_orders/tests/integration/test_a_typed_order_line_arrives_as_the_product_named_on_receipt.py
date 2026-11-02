"""An order line typed by hand arrives as the product its receiver names.

A receipt takes only products into stock: a line that names nothing on the
product list is refused when the receipt commits, and the receipt built from
an order commits as it is created. An order line typed by hand — the buyer
naming what they ordered — was for a while turned into a product of that
name by the receipt itself, unit and all, without anyone being asked. Now
whoever receives it names the product: one from the list, or one they have
just added. Without that answer the receipt is refused, naming the line; the
answer stays on the order line, so the next receipt does not ask again.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper

pytestmark = pytest.mark.integration

TYPED_NAME = 'Hand-typed widget'


def _confirmed_order(
    client: TestClient, headers: dict[str, str], partner: Any, name: str
) -> dict[str, Any]:
    po = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'partner_id': str(partner.id),
            'lines': [{'name': name, 'quantity_ordered': 4, 'unit_price': '2.00'}],
        },
    )
    assert po.status_code == status.HTTP_201_CREATED, po.text
    po_id = po.json()['id']
    client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    return dict(po.json())


def _receive(
    client: TestClient,
    headers: dict[str, str],
    po: dict[str, Any],
    location: Any,
    product_template_id: str | None = None,
) -> Any:
    body: dict[str, Any] = {'target_location_id': str(location.id)}
    if product_template_id is not None:
        body['lines'] = [
            {
                'po_line_id': po['lines'][0]['id'],
                'quantity': 2,
                'product_template_id': product_template_id,
            }
        ]
    return client.post(
        f'/api/v1/purchase-orders/{po["id"]}/create-receipt',
        headers=headers,
        json=body,
    )


def _products_named(
    client: TestClient, headers: dict[str, str], name: str
) -> list[dict[str, Any]]:
    found = client.get(
        '/api/v1/items/product-templates', headers=headers, params={'search': name}
    )
    return [p for p in found.json() if p['name'] == name]


def test_a_typed_line_received_without_a_product_is_refused_by_name(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_location: Any,
) -> None:
    po = _confirmed_order(client, po_auth_headers, po_partner, TYPED_NAME)

    receipt = _receive(client, po_auth_headers, po, po_location)

    assert receipt.status_code == status.HTTP_400_BAD_REQUEST, receipt.text
    detail = receipt.json()['detail']
    assert detail['message'].startswith(f'Line 1 ({TYPED_NAME}) names no product')
    assert detail['code'] == 'DOCUMENT_RECEIPT_LINES_NEED_PRODUCT'
    # Nobody chose to add it, so nothing was added to the product list.
    assert _products_named(client, po_auth_headers, TYPED_NAME) == []


def test_a_name_the_list_holds_is_not_taken_for_the_product_unasked(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_location: Any,
    po_template: Any,
) -> None:
    po = _confirmed_order(client, po_auth_headers, po_partner, po_template.name)

    receipt = _receive(client, po_auth_headers, po, po_location)

    assert receipt.status_code == status.HTTP_400_BAD_REQUEST, receipt.text


def test_the_named_product_arrives_and_stays_on_the_order_line(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_location: Any,
    po_template: Any,
) -> None:
    po = _confirmed_order(client, po_auth_headers, po_partner, TYPED_NAME)

    receipt = _receive(client, po_auth_headers, po, po_location, str(po_template.id))

    assert receipt.status_code == status.HTTP_201_CREATED, receipt.text
    assert receipt.json()['lines'][0]['product_template_id'] == str(po_template.id)
    order = client.get(f'/api/v1/purchase-orders/{po["id"]}', headers=po_auth_headers)
    assert order.json()['lines'][0]['product_template_id'] == str(po_template.id)
    # The rest of the line arrives as the same product without being asked.
    rest = _receive(client, po_auth_headers, po, po_location)
    assert rest.status_code == status.HTTP_201_CREATED, rest.text
    assert rest.json()['lines'][0]['product_template_id'] == str(po_template.id)


def test_another_organizations_product_is_not_a_name_for_the_line(
    client: TestClient,
    h: ModuleTestHelper,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_location: Any,
) -> None:
    elsewhere = h.create_template(
        h.create_org('Elsewhere', ['core', 'items']), name='Their widget'
    )
    po = _confirmed_order(client, po_auth_headers, po_partner, TYPED_NAME)

    receipt = _receive(client, po_auth_headers, po, po_location, str(elsewhere.id))

    assert receipt.status_code == status.HTTP_400_BAD_REQUEST, receipt.text
    assert f'1 ({TYPED_NAME})' in receipt.json()['detail']['message']


def test_the_receive_screen_leaves_its_answer_on_the_order_line(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_location: Any,
    po_template: Any,
) -> None:
    """The one-screen receive posts a whole receipt, not one built from the order.

    The product named there went onto the receipt line only, so the next
    partial delivery of the same order line asked again.
    """
    po = _confirmed_order(client, po_auth_headers, po_partner, TYPED_NAME)

    posted = client.post(
        '/api/v1/warehouse/documents/post',
        headers=po_auth_headers,
        json={
            'type': 'IN',
            'partner_id': str(po_partner.id),
            'target_location_id': str(po_location.id),
            'lines': [
                {
                    'name': TYPED_NAME,
                    'product_template_id': str(po_template.id),
                    'expected_quantity': '2',
                    'source_po_line_id': po['lines'][0]['id'],
                }
            ],
        },
    )

    assert posted.status_code == status.HTTP_201_CREATED, posted.text
    order = client.get(f'/api/v1/purchase-orders/{po["id"]}', headers=po_auth_headers)
    assert order.json()['lines'][0]['product_template_id'] == str(po_template.id)
