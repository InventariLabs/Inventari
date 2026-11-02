"""An order reads what a receipt posted against it at once.

The order learned its received quantities from the ``document.completed``
event. In production that event leaves through the outbox relay seconds
after the receipt has committed, so the order screen opened straight after
posting still said 0 of 8 received — the same order the receive screen had
just said was complete. Tests flush the event inside the request, which hid
the gap; these tests hold the event back, as production does, and ask the
order straight after the post.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.events import event_bus


@pytest.fixture
def events_held_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """No event reaches a subscriber within the request, as in production."""

    async def _not_yet(_db: Any) -> None:
        return None

    monkeypatch.setattr(event_bus, 'flush_pending', _not_yet)


def _confirmed_order(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    template_id: Any,
    quantity: int,
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'partner_id': str(partner_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'quantity_ordered': quantity,
                    'unit_price': '2.50',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = cast(str, created.json()['id'])
    confirmed = client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return cast(dict[str, Any], confirmed.json())


def _post_receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    template_id: Any,
    location_id: Any,
    order_line_id: str,
    quantity: int,
) -> None:
    posted = client.post(
        '/api/v1/warehouse/documents/post',
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
    assert posted.status_code == status.HTTP_201_CREATED, posted.text
    assert posted.json()['status'] == 'COMPLETED'


@pytest.mark.integration
@pytest.mark.usefixtures('events_held_back')
class TestTheOrderShowsAPostedReceiptAtOnce:
    def test_a_short_delivery_counts_and_leaves_the_rest_expected(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        order = _confirmed_order(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=8,
        )

        _post_receipt(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            order_line_id=order['lines'][0]['id'],
            quantity=5,
        )

        detail = client.get(
            f'/api/v1/purchase-orders/{order["id"]}', headers=po_auth_headers
        )
        assert detail.status_code == status.HTTP_200_OK, detail.text
        assert float(detail.json()['lines'][0]['quantity_received']) == 5
        assert detail.json()['status'] == 'CONFIRMED'

    def test_the_last_of_the_goods_completes_the_order(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        order = _confirmed_order(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=8,
        )
        line_id = order['lines'][0]['id']
        for quantity in (5, 3):
            _post_receipt(
                client,
                po_auth_headers,
                partner_id=po_partner.id,
                template_id=po_template.id,
                location_id=po_location.id,
                order_line_id=line_id,
                quantity=quantity,
            )

        detail = client.get(
            f'/api/v1/purchase-orders/{order["id"]}', headers=po_auth_headers
        )
        assert detail.status_code == status.HTTP_200_OK, detail.text
        assert float(detail.json()['lines'][0]['quantity_received']) == 8
        assert detail.json()['status'] == 'COMPLETED'

    @pytest.mark.parametrize('arrived', [5, 8])
    def test_held_goods_get_a_separate_replenishment_without_claiming_the_order(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
        arrived: int,
    ) -> None:
        order = _confirmed_order(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=8,
        )
        receipt = client.post(
            '/api/v1/warehouse/documents/post',
            headers=po_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(po_partner.id),
                'target_location_id': str(po_location.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'expected_quantity': arrived,
                        'source_po_line_id': order['lines'][0]['id'],
                        'batch_number': 'DAMAGED-LOT',
                        'held_quantity': 2,
                        'discrepancy_code': 'DAMAGE',
                    }
                ],
            },
        )
        assert receipt.status_code == 201, receipt.text
        assert receipt.json()['status'] == 'COMPLETED'
        documents = client.get('/api/v1/warehouse/documents', headers=po_auth_headers)
        assert documents.status_code == 200, documents.text
        drafts = [
            d
            for d in documents.json()['items']
            if d['backorder_id'] == receipt.json()['id']
        ]
        assert len(drafts) == 1
        draft = client.get(
            f'/api/v1/warehouse/documents/{drafts[0]["id"]}', headers=po_auth_headers
        ).json()
        assert draft['status'] == 'DRAFT'
        assert float(draft['lines'][0]['expected_quantity']) == 2
        assert draft['lines'][0]['source_po_line_id'] is None
        assert draft['lines'][0]['batch_number'] is None
        detail = client.get(
            f'/api/v1/purchase-orders/{order["id"]}', headers=po_auth_headers
        ).json()
        assert float(detail['lines'][0]['quantity_received']) == arrived
        assert detail['status'] == ('CONFIRMED' if arrived == 5 else 'COMPLETED')
        if arrived == 5:
            _post_receipt(
                client,
                po_auth_headers,
                partner_id=po_partner.id,
                template_id=po_template.id,
                location_id=po_location.id,
                order_line_id=order['lines'][0]['id'],
                quantity=3,
            )
        detail = client.get(
            f'/api/v1/purchase-orders/{order["id"]}', headers=po_auth_headers
        ).json()
        assert detail['status'] == 'COMPLETED'
        assert float(detail['lines'][0]['quantity_received']) == 8
