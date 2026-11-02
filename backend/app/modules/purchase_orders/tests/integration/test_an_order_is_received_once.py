"""An order line cannot be received for more than it ordered — by any door.

The guard that says so lived in one place: the endpoint that makes a receipt
out of an order. A receipt is an ordinary document, though, and
``source_po_line_id`` is a field the client fills in — so posting a receipt
straight to the documents endpoint and naming an order line on it received
whatever quantity was asked for. The order then reported more goods arrived
than were ever ordered, and its own completion arithmetic ran on that figure.

The rule belongs to the invariant, not to the endpoint: a receipt naming an
order line is checked when it is confirmed and again when it is completed,
whichever door it came in by.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization


def _receiver_headers_without_the_over_receipt_permission(
    h: ModuleTestHelper, org: Organization
) -> dict[str, str]:
    """A user who may receive but not past the tolerance.

    The ceiling is a permission boundary now, and an admin bypasses every
    permission — these tests pin the refusal on the side that does not.
    """
    user = h.create_user(org, email='plain-receiver@example.com', role='user')
    h.grant_permissions(user, ['warehouse:read', 'warehouse:write'])
    return h.get_auth_headers(user)


def _confirmed_po_line(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    template_id: Any,
    quantity: int = 10,
    uom_id: Any = None,
) -> tuple[str, str]:
    """``(po_id, po_line_id)`` for a confirmed order of *quantity*."""
    line: dict[str, Any] = {
        'product_template_id': str(template_id),
        'quantity_ordered': quantity,
        'unit_price': '2.00',
    }
    if uom_id is not None:
        line['uom_id'] = str(uom_id)
    created = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={'partner_id': str(partner_id), 'lines': [line]},
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
    uom_id: Any = None,
) -> str:
    line: dict[str, Any] = {
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
        'source_po_line_id': po_line_id,
    }
    if uom_id is not None:
        line['uom_id'] = str(uom_id)
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


@pytest.mark.integration
class TestAnOrderIsReceivedOnce:
    def test_a_hand_built_receipt_cannot_exceed_the_order(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers_without_the_over_receipt_permission(h, po_org)
        _, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=10,
        )
        doc_id = _receipt_against(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='100',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=receiver
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text

    def test_two_receipts_cannot_between_them_exceed_the_order(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        receiver = _receiver_headers_without_the_over_receipt_permission(h, po_org)
        _, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=10,
        )
        first = _receipt_against(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='6',
        )
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{first}/confirm', headers=receiver
            ).status_code
            == status.HTTP_200_OK
        )
        second = _receipt_against(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='6',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{second}/confirm', headers=receiver
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text

    def test_what_was_ordered_still_goes_through(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """The control: the guard must not refuse the ordinary case."""
        _, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            quantity=10,
        )
        doc_id = _receipt_against(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template.id,
            po_line_id=po_line_id,
            quantity='10',
        )
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=po_auth_headers
            ).status_code
            == status.HTTP_200_OK
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text


@pytest.mark.integration
class TestTheOrderAndTheReceiptSpeakOneUnit:
    """10000 g ordered; a receipt of 20 kg is twice that, however it is written.

    Compared as written, twenty was less than ten thousand and the guard let
    twice the order onto the shelf. Both sides are now put into the product's
    stock unit before they are compared.
    """

    def test_twenty_kilograms_against_ten_thousand_grams_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        h: Any,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template_with_uom: Any,
        po_location: Any,
        po_uom_kg: Any,
    ) -> None:
        receiver = _receiver_headers_without_the_over_receipt_permission(h, po_org)
        _, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template_with_uom.id,
            quantity=10000,
            uom_id=h.get_uom('g').id,
        )
        doc_id = _receipt_against(
            client,
            receiver,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template_with_uom.id,
            po_line_id=po_line_id,
            quantity='20',
            uom_id=po_uom_kg.id,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=receiver
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text

    def test_ten_kilograms_against_ten_thousand_grams_is_the_whole_order(
        self,
        client: TestClient,
        db_session: Session,
        h: Any,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template_with_uom: Any,
        po_location: Any,
        po_uom_kg: Any,
    ) -> None:
        _, po_line_id = _confirmed_po_line(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template_with_uom.id,
            quantity=10000,
            uom_id=h.get_uom('g').id,
        )
        doc_id = _receipt_against(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            location_id=po_location.id,
            template_id=po_template_with_uom.id,
            po_line_id=po_line_id,
            quantity='10',
            uom_id=po_uom_kg.id,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=po_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
