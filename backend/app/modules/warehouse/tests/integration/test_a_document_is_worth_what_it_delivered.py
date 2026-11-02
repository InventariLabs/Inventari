"""A completed document is worth what arrived, not what was ordered.

Line values were computed from ``expected_quantity`` and recomputed only when
a draft was written or a correction raised — never at completion. A delivery of
sixty against an order of a hundred stayed in the register at the value of a
hundred, and the backorder for the missing forty copied the unit price and
carried that value a second time. The chain then said a hundred and forty
units' worth of goods for a hundred units ordered, which is also the figure the
approval threshold reads.

The rule the receipt path already follows: while the document is a plan its
value is what it plans, and once it is executed its value is what it did.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _priced_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    location: StorageLocation,
    partner: Partner,
    item: Item,
    quantity: str = '10',
    unit_price: str = '5.00',
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {
                    'item_id': str(item.id),
                    'expected_quantity': quantity,
                    'unit_price': unit_price,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    created: dict[str, Any] = resp.json()
    return created


def _complete_partially(
    client: TestClient, headers: dict[str, str], doc: dict[str, Any], done: str
) -> dict[str, Any]:
    client.patch(f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=headers)
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/complete',
        headers=headers,
        json={
            'lines': [
                {
                    'line_id': doc['lines'][0]['id'],
                    'done_quantity': done,
                    'discrepancy_code': 'SHORTAGE',
                    'discrepancy_reason': 'The rest did not arrive',
                }
            ]
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    completed: dict[str, Any] = resp.json()
    return completed


def test_a_plan_is_worth_what_it_plans(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
) -> None:
    """The control: nothing is executed yet, so the order value stands."""
    doc = _priced_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )

    assert doc['total_net'] == '50.00'


def test_a_completed_document_is_worth_what_arrived(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
) -> None:
    doc = _priced_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )

    completed = _complete_partially(client, doc_auth_headers, doc, '7')

    assert completed['lines'][0]['line_value'] == '35.00'
    assert completed['total_net'] == '35.00'


def test_the_chain_adds_up_to_what_was_ordered(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
) -> None:
    """Seven delivered plus three still owed is ten, once and only once."""
    doc = _priced_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )

    completed = _complete_partially(client, doc_auth_headers, doc, '7')

    listed = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers).json()
    (backorder,) = [d for d in listed['items'] if d.get('backorder_id') == doc['id']]

    assert Decimal(completed['total_net']) + Decimal(backorder['total_net']) == Decimal(
        '50.00'
    )
