"""Goods received on a warehouse receipt are purchases in the purchase patterns.

The record a receipt opens is born with the reason ``document_execution`` and
the document type ``IN``. Purchase patterns leave out the records that were
born some other way than a purchase (an opened package, a transfer remainder),
and a receipt must not be among them: it is how a warehouse buys.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _receive(
    client: TestClient,
    headers: dict[str, str],
    partner: Any,
    target: Any,
    template: Any,
    price: str,
) -> None:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': '1',
                    'unit_price': price,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    path = f'/api/v1/warehouse/documents/{doc_id}'
    assert client.patch(f'{path}/confirm', headers=headers).status_code == 200
    done = client.patch(
        f'{path}/complete', headers=headers, json={'complete_as_planned': True}
    )
    assert done.status_code == status.HTTP_200_OK, done.text


def test_two_receipts_of_a_product_are_two_purchases(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Any,
    doc_target_location: Any,
    doc_source_location: Any,
    doc_template: Any,
) -> None:
    # A receipt into a place that already holds the product tops that record
    # up, so two purchases are two records in two places.
    for shelf, price in (
        (doc_target_location, '20.00'),
        (doc_source_location, '24.00'),
    ):
        _receive(
            client,
            doc_auth_headers,
            doc_partner,
            shelf,
            doc_template,
            price,
        )

    response = client.get('/api/v1/stats/purchase-patterns', headers=doc_auth_headers)

    assert response.status_code == status.HTTP_200_OK, response.text
    rows = {r['name']: r for r in response.json()['top_recurring_products']}
    assert doc_template.name in rows
    assert rows[doc_template.name]['total_purchases_last_6_months'] == 2
