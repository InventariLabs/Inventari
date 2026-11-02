"""The order line is where an order-linked surplus and correction land.

The over-receipt rule measures an order-linked receipt against what is
left on its order line, not against the document line's own expectation,
and a positive correction passes the same gate as the ramp. This file
holds that side: the PO event subscription, which recomputes
``quantity_received`` when a linked document completes, lives here.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization


def _receiver_headers(
    h: ModuleTestHelper,
    org: Organization,
    *,
    may_exceed: bool,
    email: str,
) -> dict[str, str]:
    user = h.create_user(org, email=email, role='user')
    permissions = ['warehouse:read', 'warehouse:write']
    if may_exceed:
        permissions.append('warehouse:receive_over_tolerance')
    h.grant_permissions(user, permissions)
    return h.get_auth_headers(user)


def _confirmed_po_line(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    template_id: Any,
    quantity: int = 10,
) -> tuple[str, str]:
    created = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'partner_id': str(partner_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'quantity_ordered': quantity,
                    'unit_price': '2.00',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = cast(str, created.json()['id'])
    confirmed = client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return po_id, cast(str, confirmed.json()['lines'][0]['id'])


def _receipt_against(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    po_line_id: str,
    quantity: str,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'source_po_line_id': po_line_id,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _complete_receipt(
    client: TestClient,
    headers: dict[str, str],
    doc: dict[str, Any],
    *,
    done_quantity: str,
) -> Any:
    return client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/complete',
        headers=headers,
        json={
            'lines': [
                {
                    'line_id': doc['lines'][0]['id'],
                    'done_quantity': done_quantity,
                    'discrepancy_code': 'SURPLUS',
                }
            ]
        },
    )


def _quantity_received(
    client: TestClient, headers: dict[str, str], po_id: str
) -> float:
    detail = client.get(f'/api/v1/purchase-orders/{po_id}', headers=headers)
    assert detail.status_code == status.HTTP_200_OK, detail.text
    return float(detail.json()['lines'][0]['quantity_received'])


@pytest.mark.integration
class TestTheOrderLineIsTheBasis:
    def test_within_tolerance_the_surplus_lands_on_the_order(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Twenty percent of ten is twelve, and twelve is what the order gets."""
        h.set_module_settings(
            po_org, 'warehouse', {'over_receipt_tolerance_percent': 20}
        )
        receiver = _receiver_headers(
            h, po_org, may_exceed=False, email='order-tolerance@example.com'
        )
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        doc = _receipt_against(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='10',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=receiver
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        complete = _complete_receipt(client, receiver, doc, done_quantity='12')
        assert complete.status_code == status.HTTP_200_OK, complete.text

        assert _quantity_received(client, po_auth_headers, po_id) == 12

    def test_past_tolerance_needs_the_permission(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers(
            h, po_org, may_exceed=False, email='order-refused@example.com'
        )
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        doc = _receipt_against(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='10',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=receiver
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        complete = _complete_receipt(client, receiver, doc, done_quantity='12')
        assert complete.status_code == status.HTTP_400_BAD_REQUEST, complete.text
        assert 'order' in complete.text
        assert 'receive over tolerance' in complete.text

    def test_a_permission_holder_may_go_past_it_and_the_order_follows(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers(
            h, po_org, may_exceed=True, email='order-allowed@example.com'
        )
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        doc = _receipt_against(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='10',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=receiver
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        complete = _complete_receipt(client, receiver, doc, done_quantity='12')
        assert complete.status_code == status.HTTP_200_OK, complete.text
        assert _quantity_received(client, po_auth_headers, po_id) == 12


def _post_in_one_step(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    po_line_id: str,
    quantity: str,
    confirm: bool = False,
) -> Any:
    return client.post(
        '/api/v1/warehouse/documents/post',
        headers=headers,
        params={'confirm_surplus': 'true'} if confirm else None,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'source_po_line_id': po_line_id,
                    'discrepancy_code': 'SURPLUS',
                }
            ],
        },
    )


@pytest.mark.integration
class TestTheOneStepDoorAsksTheSameQuestion:
    """Creating and posting in one call weighs the surplus as the draft door does.

    The one-screen receive posts through this door; a permission the draft
    door honours must not stop working because the receipt was never a
    draft.
    """

    def test_without_the_permission_it_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers(
            h, po_org, may_exceed=False, email='one-step-refused@example.com'
        )
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )

        posted = _post_in_one_step(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='12',
            confirm=True,
        )

        assert posted.status_code == status.HTTP_400_BAD_REQUEST, posted.text
        assert 'receive over tolerance' in posted.text
        assert _quantity_received(client, po_auth_headers, po_id) == 0

    def test_the_holder_is_asked_naming_the_order_line_then_it_posts(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers(
            h, po_org, may_exceed=True, email='one-step-asked@example.com'
        )
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        order_number = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        ).json()['number']
        press = {
            'partner_id': po_partner.id,
            'location_id': po_location.id,
            'template_id': po_template.id,
            'po_line_id': po_line_id,
            'quantity': '12',
        }

        asked = _post_in_one_step(client, receiver, **press)

        assert asked.status_code == status.HTTP_409_CONFLICT, asked.text
        detail = asked.json()['detail']
        assert detail['code'] == 'SURPLUS_NEEDS_CONFIRMATION'
        assert detail['message'] == (
            f'{po_template.name}: receiving 12 is 2 more than the 10 left on '
            f'order {order_number}, line 1. Receive the surplus?'
        )
        assert _quantity_received(client, po_auth_headers, po_id) == 0

        posted = _post_in_one_step(client, receiver, **press, confirm=True)

        assert posted.status_code == status.HTTP_201_CREATED, posted.text
        assert _quantity_received(client, po_auth_headers, po_id) == 12

    def test_past_the_ceiling_even_the_holder_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        h.set_module_settings(po_org, 'warehouse', {'over_receipt_ceiling_percent': 10})
        receiver = _receiver_headers(
            h, po_org, may_exceed=True, email='one-step-ceiling@example.com'
        )
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )

        posted = _post_in_one_step(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='12',
            confirm=True,
        )

        assert posted.status_code == status.HTTP_400_BAD_REQUEST, posted.text
        assert '10% over-receipt ceiling' in posted.text
        assert _quantity_received(client, po_auth_headers, po_id) == 0

    def test_two_surpluses_are_both_named_before_one_yes_takes_them(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        # The yes lifts the tolerance for the whole receipt, so a question
        # that stopped at the first surplus let the second one through
        # unasked: 6 -> 8 was named, 2 -> 20 went in on the same answer.
        receiver = _receiver_headers(
            h, po_org, may_exceed=True, email='one-step-two-surpluses@example.com'
        )
        created = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': ordered,
                        'unit_price': '2.00',
                    }
                    for ordered in (6, 2)
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']
        confirmed = client.post(
            f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        order = confirmed.json()

        asked = client.post(
            '/api/v1/warehouse/documents/post',
            headers=receiver,
            json={
                'type': 'IN',
                'partner_id': str(po_partner.id),
                'target_location_id': str(po_location.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'expected_quantity': received,
                        'source_po_line_id': line['id'],
                        'discrepancy_code': 'SURPLUS',
                    }
                    for line, received in zip(order['lines'], ('8', '20'), strict=True)
                ],
            },
        )

        assert asked.status_code == status.HTTP_409_CONFLICT, asked.text
        assert asked.json()['detail']['message'] == (
            f'{po_template.name}: receiving 8 is 2 more than the 6 left on '
            f'order {order["number"]}, line 1. Receive the surplus? '
            f'{po_template.name}: receiving 20 is 18 more than the 2 left on '
            f'order {order["number"]}, line 2. Receive the surplus?'
        )


@pytest.mark.integration
class TestACorrectionReachesTheOrderItCorrects:
    """A correction line names its order line, so the order moves by it."""

    def _closed_receipt(
        self,
        client: TestClient,
        headers: dict[str, str],
        *,
        partner_id: Any,
        location_id: Any,
        template_id: Any,
        po_line_id: str,
        quantity: str = '10',
    ) -> dict[str, Any]:
        doc = _receipt_against(
            client,
            headers,
            partner_id=partner_id,
            location_id=location_id,
            template_id=template_id,
            po_line_id=po_line_id,
            quantity=quantity,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        return doc

    def _run_correction(
        self,
        client: TestClient,
        headers: dict[str, str],
        *,
        original: dict[str, Any],
        delta: str,
    ) -> Any:
        created = client.post(
            '/api/v1/warehouse/corrections',
            headers=headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': delta}],
            },
        )
        if created.status_code != status.HTTP_201_CREATED:
            return created
        correction_id = created.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/confirm', headers=headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        return client.patch(
            f'/api/v1/warehouse/documents/{correction_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )

    def test_a_positive_correction_raises_the_order_figure(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        receipt = self._closed_receipt(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
        )
        assert _quantity_received(client, po_auth_headers, po_id) == 10

        completed = self._run_correction(
            client, po_auth_headers, original=receipt, delta='2'
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
        assert _quantity_received(client, po_auth_headers, po_id) == 12

    def test_a_counter_correction_takes_it_back_off(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        receipt = self._closed_receipt(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
        )
        up = self._run_correction(client, po_auth_headers, original=receipt, delta='2')
        assert up.status_code == status.HTTP_200_OK, up.text
        assert _quantity_received(client, po_auth_headers, po_id) == 12

        # A reversal of the same line — minus two against the receipt — takes
        # the delta back off the order.
        down = self._run_correction(
            client, po_auth_headers, original=receipt, delta='-2'
        )
        assert down.status_code == status.HTTP_200_OK, down.text
        assert _quantity_received(client, po_auth_headers, po_id) == 10

    def test_a_surplus_correction_without_the_permission_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers(
            h, po_org, may_exceed=False, email='order-correction-refused@example.com'
        )
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        receipt = self._closed_receipt(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
        )
        refused = client.post(
            '/api/v1/warehouse/corrections',
            headers=receiver,
            json={
                'corrects_document_id': receipt['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': '2'}],
            },
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'over-receipt tolerance' in refused.text
        assert _quantity_received(client, po_auth_headers, po_id) == 10


class TestHeldGoodsAreDeliveredToTheOrder:
    """What a receipt quarantines still arrived, so the order stops waiting.

    A batch that arrived with part of it held back is still one batch, so the
    stock stays together and is blocked; the order counts the whole delivery,
    because the goods are in the building and wait for a decision, not for
    the supplier. The held part has a separate replacement draft; goods that
    never arrived remain owed on the order.
    """

    def test_the_held_quantity_is_counted_as_received(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        po_id, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
        )
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=po_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(po_partner.id),
                'target_location_id': str(po_location.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'expected_quantity': '10',
                        'source_po_line_id': po_line_id,
                        'batch_number': 'ORDER-HELD-1',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        receipt = created.json()
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{receipt["id"]}/confirm',
            headers=po_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        completed = client.patch(
            f'/api/v1/warehouse/documents/{receipt["id"]}/complete',
            headers=po_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': receipt['lines'][0]['id'],
                        'done_quantity': '7',
                        'held_quantity': '3',
                        'discrepancy_code': 'DAMAGE',
                        'discrepancy_reason': 'Three crates crushed',
                    }
                ]
            },
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

        assert _quantity_received(client, po_auth_headers, po_id) == 7
        backorders = [
            doc
            for doc in client.get(
                '/api/v1/warehouse/documents', headers=po_auth_headers
            ).json()['items']
            if doc.get('backorder_id') == receipt['id']
        ]
        assert len(backorders) == 1
        draft = client.get(
            f'/api/v1/warehouse/documents/{backorders[0]["id"]}',
            headers=po_auth_headers,
        )
        assert draft.status_code == status.HTTP_200_OK, draft.text
        assert float(draft.json()['lines'][0]['expected_quantity']) == 3
        assert draft.json()['lines'][0]['source_po_line_id'] is None
