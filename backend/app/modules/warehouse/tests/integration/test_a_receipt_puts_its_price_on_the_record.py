"""The price a receipt was posted at is on the record it opened.

A delivery of ten at 5.14 posted a cost layer of 51.40 and opened a record
in the target location with no purchase price at all. The product screen
has a "purchase price per unit" field; for goods that arrived by document
it stayed empty although the document had just said the price.

The layer stays the source of truth for what the stock is worth. The price
on the record is what it has always been: the figure a person sees on the
card, and the fallback for an organization that keeps no layers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _received(
    client: TestClient,
    headers: dict[str, str],
    *,
    header: dict[str, Any],
    line: dict[str, Any],
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={'type': 'IN', **header, 'lines': [line]},
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    assert (
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        ).status_code
        == 200
    )
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text
    return cast(dict[str, Any], done.json())


def _record(
    client: TestClient, headers: dict[str, str], item_id: str
) -> dict[str, Any]:
    resp = client.get(f'/api/v1/items/{item_id}', headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


class TestTheRecordSaysWhatItCost:
    def test_a_product_line_opens_a_record_with_its_price(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: Any,
        doc_template: Any,
    ) -> None:
        doc = _received(
            client,
            doc_auth_headers,
            header={
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
            },
            line={
                'product_template_id': str(doc_template.id),
                'expected_quantity': '10',
                'unit_price': '5.14',
            },
        )
        record = _record(client, doc_auth_headers, doc['lines'][0]['item_id'])

        assert Decimal(record['purchase_price']) == Decimal('5.14')
        # A record is denominated in the organization's money; a document
        # typed by hand is too, so the two agree.
        assert record['currency'] == doc['currency']
