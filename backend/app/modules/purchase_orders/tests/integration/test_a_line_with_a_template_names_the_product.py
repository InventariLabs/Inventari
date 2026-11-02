"""A line created with a product template and no name answers with the name.

The UI always sends a line name; the API path does not have to, and the stored
column kept the empty string it was given, leaving the order with a row that
named nothing. The response now resolves the template's name -- the way
``ReorderRuleSchema`` resolves ``product_name`` -- while a line that carries
its own name keeps exactly what it carries.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def test_a_line_with_a_template_and_no_name_answers_with_the_product_s_name(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_template: Any,
) -> None:
    po = client.post(
        '/api/v1/purchase-orders',
        headers=po_auth_headers,
        json={
            'partner_id': str(po_partner.id),
            'lines': [
                {
                    'product_template_id': str(po_template.id),
                    'quantity_ordered': '3',
                },
                {
                    'product_template_id': str(po_template.id),
                    'name': 'Named by the caller',
                    'quantity_ordered': '1',
                },
            ],
        },
    )
    assert po.status_code == status.HTTP_201_CREATED, po.text
    unnamed, named = po.json()['lines']
    assert unnamed['name'] == po_template.name
    assert named['name'] == 'Named by the caller'

    fetched = client.get(
        f'/api/v1/purchase-orders/{po.json()["id"]}', headers=po_auth_headers
    )
    assert fetched.status_code == status.HTTP_200_OK, fetched.text
    assert fetched.json()['lines'][0]['name'] == po_template.name
