"""A receipt made from an order is denominated in the order's currency.

The receipt copied every unit price off the order digit for digit and then
stamped the header with the organization's currency. An order of 100 × 40.10
PLN became a receipt reading '$601.50' — the same numbers under a different
sign, with nothing converted and nothing said.

The document carries its own currency now. It keeps it for its whole life
without any further guarding: a receipt from an order is born CONFIRMED, and
only a DRAFT document can have its lines — and with them its currency —
rewritten.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization


def _confirmed_po(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    template_id: Any,
    currency: str | None,
    unit_price: str = '40.10',
    quantity: int = 100,
) -> str:
    body: dict[str, Any] = {
        'partner_id': str(partner_id),
        'lines': [
            {
                'product_template_id': str(template_id),
                'quantity_ordered': quantity,
                'unit_price': unit_price,
            }
        ],
    }
    if currency is not None:
        body['currency'] = currency

    created = client.post('/api/v1/purchase-orders', headers=headers, json=body)
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = cast(str, created.json()['id'])

    confirmed = client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return po_id


@pytest.mark.integration
class TestReceiptCurrencyFromPurchaseOrder:
    def test_receipt_inherits_the_order_currency_not_the_organization_one(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        po_org.currency = 'USD'
        db_session.add(po_org)
        db_session.commit()

        po_id = _confirmed_po(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            currency='PLN',
        )

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert receipt.status_code == status.HTTP_201_CREATED, receipt.text

        data = receipt.json()
        assert data['currency'] == 'PLN'
        assert float(data['lines'][0]['unit_price']) == pytest.approx(40.10)

    def test_one_screen_post_carries_the_currency_of_the_order_lines_it_names(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """A receipt posted in one call keeps the order's sign, not the org's.

        The one-screen receive screen sends the whole receipt to
        ``/warehouse/documents/post`` and names the order line each row came from.
        There is no caller left to pass the order's currency, so the
        document reads it off the lines it names.
        """
        po_org.currency = 'USD'
        db_session.add(po_org)
        db_session.commit()

        po_id = _confirmed_po(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            currency='PLN',
        )
        order = client.get(f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers)
        assert order.status_code == status.HTTP_200_OK, order.text
        order_line = order.json()['lines'][0]

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
                        'expected_quantity': 100,
                        'unit_price': '40.10',
                        'source_po_line_id': order_line['id'],
                    }
                ],
            },
        )
        assert posted.status_code == status.HTTP_201_CREATED, posted.text
        data = posted.json()
        assert data['currency'] == 'PLN'
        assert float(data['lines'][0]['unit_price']) == pytest.approx(40.10)

    def test_receipt_keeps_the_organization_currency_when_the_order_names_none(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """No inherited currency means the old answer is still the right one."""
        po_org.currency = 'EUR'
        db_session.add(po_org)
        db_session.commit()

        po_id = _confirmed_po(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            currency=None,
        )

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert receipt.status_code == status.HTTP_201_CREATED, receipt.text
        assert receipt.json()['currency'] == 'EUR'
