"""Receiving an order's delivery one item at a time, on the phone.

The phone saves the receive sheet as a receipt, confirms it and opens its
receiving session. A line the order asked for is received against what the
order still owes; a line nobody ordered carries the count the worker wrote
down, and the card must tell the two apart.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization


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
                    'unit_price': '3.00',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = cast(str, created.json()['id'])
    confirmed = client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return cast(dict[str, Any], confirmed.json())


def _session_for(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    lines: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """The receipt the phone saves and confirms, with its session started."""
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': lines,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    started = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert started.status_code == status.HTTP_201_CREATED, started.text
    return doc_id, cast(dict[str, Any], started.json())


@pytest.mark.integration
class TestTheCardSaysWhatWasOrdered:
    def test_only_a_line_from_the_order_reads_as_ordered(
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
            quantity=6,
        )
        _doc_id, session = _session_for(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            lines=[
                {
                    'product_template_id': str(po_template.id),
                    'expected_quantity': '6',
                    'source_po_line_id': order['lines'][0]['id'],
                },
                # The same product again, counted by the worker with no
                # order behind it: three nobody ordered.
                {
                    'product_template_id': str(po_template.id),
                    'expected_quantity': '3',
                },
            ],
        )

        by_quantity = {
            line['expected_quantity']: line['from_order'] for line in session['lines']
        }
        assert by_quantity == {6: True, 3: False}


def _receiver(h: ModuleTestHelper, org: Organization) -> dict[str, str]:
    """Someone who may receive, and may not receive over tolerance."""
    user = h.create_user(org, email='phone-receiver@example.com', role='user')
    h.grant_permissions(user, ['warehouse:read', 'warehouse:write'])
    return h.get_auth_headers(user)


@pytest.mark.integration
class TestTheRestOfAShortDelivery:
    def test_the_order_expects_the_rest_and_takes_it_in_one_post(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Four of six on the phone, then the last two from the order.

        The short receipt used to leave a draft backorder for the two the
        order already expected. Receiving them from the order then built a
        second receipt for two: refused for anyone who may not receive over
        tolerance, because the draft counted as spoken for, and left behind
        as a stale document describing goods that had arrived for anyone
        who could. The order is the expectation; the rest is received from
        it in one post — the screen the order's Receive delivery opens.
        """
        receiver = _receiver(h, po_org)
        order = _confirmed_order(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=6,
        )
        po_line_id = order['lines'][0]['id']
        doc_id, session = _session_for(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            lines=[
                {
                    'product_template_id': str(po_template.id),
                    'expected_quantity': '6',
                    'source_po_line_id': po_line_id,
                }
            ],
        )
        short = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}'
            '/short-receive',
            headers=receiver,
            json={
                'line_id': session['lines'][0]['id'],
                'received_quantity': '4',
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert short.status_code == status.HTTP_200_OK, short.text
        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=receiver
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
        assert completed.json()['generated_backorder_id'] is None

        rest = client.post(
            '/api/v1/warehouse/documents/post',
            headers=receiver,
            json={
                'type': 'IN',
                'partner_id': str(po_partner.id),
                'target_location_id': str(po_location.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'expected_quantity': '2',
                        'source_po_line_id': po_line_id,
                    }
                ],
            },
        )

        assert rest.status_code == status.HTTP_201_CREATED, rest.text
        detail = client.get(
            f'/api/v1/purchase-orders/{order["id"]}', headers=po_auth_headers
        ).json()
        assert detail['status'] == 'COMPLETED'
        receipts = client.get(
            f'/api/v1/purchase-orders/{order["id"]}/linked-receipts',
            headers=po_auth_headers,
        ).json()['items']
        assert sorted(r['status'] for r in receipts) == ['COMPLETED', 'COMPLETED']


def _stock_at(
    client: TestClient, headers: dict[str, str], template: Any, location: Any
) -> Decimal:
    resp = client.get(
        '/api/v1/stock-quants',
        headers=headers,
        params={
            'product_template_id': str(template.id),
            'location_id': str(location.id),
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return sum((Decimal(row['quantity']) for row in resp.json()['items']), Decimal(0))


@pytest.mark.integration
class TestDamagedGoodsOnTheOneScreenReceipt:
    def test_two_damaged_of_twenty_are_held_and_the_order_counts_twenty(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_user: Any,
        po_storage_type: Any,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Twenty arrived, two of them damaged: one press says so.

        The one-screen receipt had a count and nothing else, so the storekeeper
        chose between receiving eighteen (the two damaged ones then stood
        "on the way" with no reason) and receiving twenty into stock. The
        line now says how much of what arrived is held and why: that part
        goes to the quarantine shelf, the rest is available, and the order
        counts the whole delivery: it stops waiting for goods that are in
        the building and waits for a decision, not for a supplier.
        """
        quarantine = h.create_storage_location(
            po_org, po_storage_type, po_user, name='Quarantine'
        )
        named = client.put(
            '/api/v1/warehouse/profile',
            headers=po_auth_headers,
            json={'quarantine_location_id': str(quarantine.id)},
        )
        assert named.status_code == status.HTTP_200_OK, named.text
        order = _confirmed_order(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=20,
        )

        posted = client.post(
            '/api/v1/warehouse/documents/post',
            headers=po_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(po_partner.id),
                'target_location_id': str(po_location.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'expected_quantity': '20',
                        'source_po_line_id': order['lines'][0]['id'],
                        'held_quantity': '2',
                        'discrepancy_code': 'DAMAGE',
                        'discrepancy_reason': 'Crushed boxes',
                    }
                ],
            },
        )

        assert posted.status_code == status.HTTP_201_CREATED, posted.text
        line = posted.json()['lines'][0]
        assert Decimal(line['held_quantity']) == Decimal(2)
        assert line['discrepancy_code'] == 'DAMAGE'
        assert Decimal(line['done_quantity']) == Decimal(20)
        assert _stock_at(client, po_auth_headers, po_template, po_location) == 18
        assert _stock_at(client, po_auth_headers, po_template, quarantine) == 2
        detail = client.get(
            f'/api/v1/purchase-orders/{order["id"]}', headers=po_auth_headers
        ).json()
        assert Decimal(detail['lines'][0]['quantity_received']) == Decimal(20)
        assert detail['status'] == 'COMPLETED'

    def test_a_held_quantity_without_a_code_is_refused_and_writes_nothing(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        posted = client.post(
            '/api/v1/warehouse/documents/post',
            headers=po_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(po_partner.id),
                'target_location_id': str(po_location.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'expected_quantity': '20',
                        'held_quantity': '2',
                    }
                ],
            },
        )

        assert posted.status_code == status.HTTP_400_BAD_REQUEST, posted.text
        assert _stock_at(client, po_auth_headers, po_template, po_location) == 0
