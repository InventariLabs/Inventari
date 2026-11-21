"""The order's receipts say which of them still hold goods the order owes.

The receive screen warns that an order already has an open receipt holding
part of what it still owes, and offers to receive the rest through it. A
receipt counts for that only when it is a receipt and one of its lines
still expects goods on an order line that is still owed: a draft for a
product the order no longer expects, or a correction of an earlier receipt,
holds none of it, and naming it sends the reader to the wrong paper.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper


def _confirmed_order(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    coffee_id: Any,
    tea_id: Any,
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'partner_id': str(partner_id),
            'lines': [
                {
                    'product_template_id': str(coffee_id),
                    'quantity_ordered': 10,
                    'unit_price': '45.00',
                },
                {
                    'product_template_id': str(tea_id),
                    'quantity_ordered': 5,
                    'unit_price': '3.20',
                },
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = cast(str, created.json()['id'])
    confirmed = client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return cast(dict[str, Any], confirmed.json())


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    order_line_id: str,
    quantity: int,
    post: bool,
) -> str:
    response = client.post(
        '/api/v1/warehouse/documents/post' if post else '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'source_po_line_id': order_line_id,
                }
            ],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return cast(str, response.json()['id'])


@pytest.mark.integration
def test_only_a_receipt_of_owed_goods_holds_what_the_order_owes(
    client: TestClient,
    h: ModuleTestHelper,
    po_org: Any,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_template: Any,
    po_location: Any,
) -> None:
    tea = h.create_template(po_org, name='Black tea', barcode=None)
    order = _confirmed_order(
        client,
        po_auth_headers,
        partner_id=po_partner.id,
        coffee_id=po_template.id,
        tea_id=tea.id,
    )
    coffee_line, tea_line = (line['id'] for line in order['lines'])
    common = {
        'partner_id': po_partner.id,
        'location_id': po_location.id,
    }
    # All the tea arrives: the order no longer owes any.
    _receipt(
        client,
        po_auth_headers,
        **common,
        template_id=tea.id,
        order_line_id=tea_line,
        quantity=5,
        post=True,
    )
    tea_draft = _receipt(
        client,
        po_auth_headers,
        **common,
        template_id=tea.id,
        order_line_id=tea_line,
        quantity=1,
        post=False,
    )
    coffee_draft = _receipt(
        client,
        po_auth_headers,
        **common,
        template_id=po_template.id,
        order_line_id=coffee_line,
        quantity=4,
        post=False,
    )

    listed = client.get(
        f'/api/v1/purchase-orders/{order["id"]}/linked-receipts',
        headers=po_auth_headers,
    )

    assert listed.status_code == status.HTTP_200_OK, listed.text
    holds = {row['id']: row['holds_owed_goods'] for row in listed.json()['items']}
    assert holds[coffee_draft] is True
    assert holds[tea_draft] is False, 'the order owes no tea'
    assert sum(holds.values()) == 1, 'the posted tea receipt holds nothing owed'
