"""A cost layer says which currency it is in.

An earlier change gave the receipt document the order's currency, so the register
shows the right sign. What it could not reach was the cost history:
``_record_receipt_valuation`` wrote ``line.unit_price`` into a
``StockValuationLayer`` that had no currency column at all. A receipt of
100 x 40.10 PLN into an organization keeping USD put 40.10 into the costs,
and every reader downstream took it for dollars.

Contrast in the same application: ``cost_service`` short-circuits a mixed
batch of supplier prices to "missing cost", and ``partner_service`` leaves
the total empty when turnover spans two currencies. The application has an
answer to this question — do not guess, say you do not know — and the
valuation layer was the one place with no way to ask it.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.stock_valuation_layer import StockValuationLayer


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    template_id: Any,
    location_id: Any,
    currency: str | None,
    unit_price: str = '40.10',
) -> str:
    """Order → confirm → receipt → complete, which is what writes the layer."""
    body: dict[str, Any] = {
        'partner_id': str(partner_id),
        'lines': [
            {
                'product_template_id': str(template_id),
                'quantity_ordered': 100,
                'unit_price': unit_price,
            }
        ],
    }
    if currency is not None:
        body['currency'] = currency

    created = client.post('/api/v1/purchase-orders', headers=headers, json=body)
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = created.json()['id']

    confirmed = client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    receipt = client.post(
        f'/api/v1/purchase-orders/{po_id}/create-receipt',
        headers=headers,
        json={'target_location_id': str(location_id)},
    )
    assert receipt.status_code == status.HTTP_201_CREATED, receipt.text
    doc_id = cast(str, receipt.json()['id'])

    completed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    return doc_id


def _layers(db: Session, template_id: Any) -> list[StockValuationLayer]:
    return list(
        db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == template_id
            )
        ).all()
    )


def _rate(client: TestClient, headers: dict[str, str], template_id: Any) -> Any:
    """This organization's AVCO rate, asked for the way the screen asks.

    Read through the API rather than off the row: the rate used to be a cached
    column on `product_templates`, which a global template shares with every
    organization, so the figure there belonged to whoever wrote last. It is
    computed per organization now, and this endpoint is where a reader gets it.
    """
    response = client.get(
        f'/api/v1/items/product-templates/{template_id}', headers=headers
    )
    assert response.status_code == status.HTTP_200_OK
    return response.json()['current_valuation_rate']


@pytest.mark.integration
class TestTheCostHistoryKnowsItsCurrency:
    def test_a_receipt_in_the_supplier_s_currency_says_so(
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

        _receive(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            currency='PLN',
        )

        layers = _layers(db_session, po_template.id)
        assert layers, 'the receipt recorded no cost layer at all'
        assert {layer.currency for layer in layers} == {'PLN'}

    def test_a_receipt_in_the_house_currency_says_that(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Left unsaid the layer would carry the old, unrecorded assumption."""
        po_org.currency = 'EUR'
        db_session.add(po_org)
        db_session.commit()

        _receive(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            currency=None,
        )

        layers = _layers(db_session, po_template.id)
        assert {layer.currency for layer in layers} == {'EUR'}

    def test_a_rate_is_not_offered_for_stock_bought_in_two_currencies(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """One number cannot stand for złoty and dollars at once."""
        po_org.currency = 'USD'
        db_session.add(po_org)
        db_session.commit()

        _receive(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            currency='USD',
            unit_price='10.00',
        )
        db_session.expire_all()
        assert _rate(client, po_auth_headers, po_template.id) is not None, (
            'a single-currency receipt should still produce a rate'
        )

        _receive(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            currency='PLN',
            unit_price='40.10',
        )

        db_session.expire_all()
        assert _rate(client, po_auth_headers, po_template.id) is None, (
            'a blended rate across two currencies is a number nobody can read'
        )

    def test_a_rate_is_not_offered_for_stock_bought_in_one_foreign_currency(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """All of it in one foreign currency is still none of it in ours.

        The mixed batch was refused, and a unanimous foreign currency used to
        slip past that guard: one currency agrees with itself, so a bare
        number came back — and every reader of the rate takes it for the
        organization's own, which is how 40.10 złoty was read as dollars.
        """
        po_org.currency = 'USD'
        db_session.add(po_org)
        db_session.commit()

        _receive(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            template_id=po_template.id,
            location_id=po_location.id,
            currency='PLN',
            unit_price='40.10',
        )

        db_session.expire_all()
        assert _rate(client, po_auth_headers, po_template.id) is None, (
            'a unanimous foreign currency is still not the house currency'
        )
