"""The products list footer moves when a delivery is posted.

Ten cocoa at 5.00 with 15.00 of freight cost 65.00, and the cost ledger said
so to the cent. The footer under the products list said the same figure as
before the delivery, because it summed the price typed on each record and a
receipt by document writes none of its own. Beside it, "Stock on a date"
and "Statistics" had already moved by 65.00.

The footer now reads the ledger, like the two screens next to it.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _footer(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get('/api/v1/items/aggregates', headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json())


def _deliver_with_freight(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: str,
    location_id: str,
    template_id: str,
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': partner_id,
            'target_location_id': location_id,
            'lines': [
                {
                    'product_template_id': template_id,
                    'expected_quantity': '10',
                    'unit_price': '5.00',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    freight = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
        headers=headers,
        json={'kind': 'freight', 'amount': '15.00'},
    )
    assert freight.status_code == status.HTTP_201_CREATED, freight.text
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
    return str(done.json()['lines'][0]['item_id'])


class TestTheFooterMovesWithTheDelivery:
    def test_a_priced_delivery_moves_the_footer_by_what_it_cost(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: Any,
        doc_template: Any,
    ) -> None:
        before = _footer(client, doc_auth_headers)['total_value']

        item_id = _deliver_with_freight(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            location_id=str(doc_target_location.id),
            template_id=str(doc_template.id),
        )

        after = _footer(client, doc_auth_headers)
        # 10 x 5.00 plus 15.00 of freight: the landed cost, as the layer holds it.
        assert after['total_value'] == pytest.approx(before + 65.0)
        assert after['value_source'] == 'valuation_layers'

        # A price corrected on the card is not a purchase; the footer stands.
        repriced = client.put(
            f'/api/v1/items/{item_id}',
            headers=doc_auth_headers,
            json={'purchase_price': '99.00'},
        )
        assert repriced.status_code == status.HTTP_200_OK, repriced.text
        assert _footer(client, doc_auth_headers)['total_value'] == pytest.approx(
            before + 65.0
        )
