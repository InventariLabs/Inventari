"""An order line takes the rate its goods name, as a document line does.

Orders price lines the way receipts do, so bread ordered from a mill
carries the reduced rate the product names, and an edited order keeps
taking it. A rate typed on the line stays. Whether lines are taxed at all
is the documents' tax handling, read from the same profile.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/purchase-orders'
RATES = '/api/v1/warehouse/tax-rates'


def _lines(bread: Any, soap: Any) -> list[dict[str, Any]]:
    return [
        {
            'product_template_id': str(bread.id),
            'quantity_ordered': '10',
            'unit_price': '2.00',
        },
        {
            'product_template_id': str(soap.id),
            'quantity_ordered': '1',
            'unit_price': '5.00',
            'tax_rate': '19.00',
        },
    ]


def test_an_order_line_takes_the_products_rate_on_create_and_on_edit(
    client: TestClient,
    db_session: Session,
    h: ModuleTestHelper,
    po_org: Organization,
    po_auth_headers: dict[str, str],
    po_partner: Any,
    po_template: Any,
) -> None:
    """Fails without the fix: the bread line was stored without a rate."""
    po_org.country = 'DE'
    db_session.commit()
    preset = client.post(
        '/api/v1/warehouse/profile/apply-preset/Full Value', headers=po_auth_headers
    )
    assert preset.status_code == status.HTTP_200_OK, preset.text
    created = client.post(
        RATES, json={'name': 'USt. 7%', 'rate': '7.00'}, headers=po_auth_headers
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    reduced = created.json()['id']
    soap = h.create_template(po_org, name='Soap', barcode='4009876543210')
    named = client.put(
        f'{RATES}/products/{po_template.id}',
        json={'tax_rate_id': reduced},
        headers=po_auth_headers,
    )
    assert named.status_code == status.HTTP_200_OK, named.text

    po = client.post(
        ORDERS,
        headers=po_auth_headers,
        json={'partner_id': str(po_partner.id), 'lines': _lines(po_template, soap)},
    )
    assert po.status_code == status.HTTP_201_CREATED, po.text
    assert [line['tax_rate'] for line in po.json()['lines']] == ['7.00', '19.00']

    edited = client.patch(
        f'{ORDERS}/{po.json()["id"]}',
        headers=po_auth_headers,
        json={'lines': _lines(po_template, soap)},
    )
    assert edited.status_code == status.HTTP_200_OK, edited.text
    assert [line['tax_rate'] for line in edited.json()['lines']] == ['7.00', '19.00']
