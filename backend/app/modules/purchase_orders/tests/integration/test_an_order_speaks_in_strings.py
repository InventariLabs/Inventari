"""An order and the receipt made from it send quantities and money as strings.

The receipt schema carried the last ``Decimal -> float`` serializer in the
application after the wire contract was unified, and nothing noticed because
the tests compared values, not shapes. This test pins the shape.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _is_decimal_string(value: object) -> bool:
    return isinstance(value, str) and value.replace('.', '', 1).isdigit()


def test_the_order_and_its_receipt_send_strings(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_template: Any,
    po_location: Any,
) -> None:
    po = client.post(
        '/api/v1/purchase-orders',
        headers=po_auth_headers,
        json={
            'partner_id': str(po_partner.id),
            'lines': [
                {
                    'product_template_id': str(po_template.id),
                    'quantity_ordered': '12.5',
                    'unit_price': '10.25',
                    'tax_rate': '23',
                }
            ],
        },
    )
    assert po.status_code == status.HTTP_201_CREATED, po.text
    body = po.json()
    line = body['lines'][0]
    assert _is_decimal_string(line['quantity_ordered']), line['quantity_ordered']
    assert _is_decimal_string(line['unit_price']), line['unit_price']
    for field in ('total_net', 'total_tax', 'total_gross'):
        assert _is_decimal_string(body[field]), (field, body[field])

    client.post(
        f'/api/v1/purchase-orders/{body["id"]}/confirm', headers=po_auth_headers
    )
    receipt = client.post(
        f'/api/v1/purchase-orders/{body["id"]}/create-receipt',
        headers=po_auth_headers,
        json={
            'target_location_id': str(po_location.id),
            'lines': [{'po_line_id': line['id'], 'quantity': '12.5'}],
        },
    )
    assert receipt.status_code == status.HTTP_201_CREATED, receipt.text
    received = receipt.json()['lines'][0]
    for field in ('quantity', 'expected_quantity', 'done_quantity', 'unit_price'):
        assert _is_decimal_string(received[field]), (field, received[field])
