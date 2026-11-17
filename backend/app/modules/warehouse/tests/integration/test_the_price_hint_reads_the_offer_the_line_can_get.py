"""A document's price hint names the supplier price the line can actually get.

The hint took the lowest unit price over a partner's whole price list: the
1000-piece tier for a line of five, an expired promotion, a price quoted in
another currency. Each is a number the supplier would not charge for this
line, written into the form as if it were.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.modules.purchase_orders.models import PartnerPricelist


@pytest.fixture
def doc_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Price Hint Org',
        [
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
            'approvals',
        ],
    )


def _offer(
    db: Session,
    org: Organization,
    partner: Partner,
    template: ProductTemplate,
    price: str,
    *,
    currency: str | None = None,
    min_quantity: str | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> None:
    db.add(
        PartnerPricelist(
            organization_id=org.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal(price),
            currency=currency or org.currency,
            min_quantity=Decimal(min_quantity) if min_quantity else None,
            valid_from=valid_from or date.today() - timedelta(days=30),
            valid_to=valid_to,
        )
    )
    db.commit()


def _hint(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    template: ProductTemplate,
    **params: str,
) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/price-hint',
        headers=headers,
        params={
            'template_id': str(template.id),
            'partner_id': str(partner.id),
            **params,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body: dict[str, Any] = response.json()
    return body


class TestThePriceHintReadsTheOfferTheLineCanGet:
    def test_a_volume_tier_the_quantity_does_not_reach_is_not_suggested(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        _offer(db_session, doc_org, doc_partner, doc_template, '3.00')
        _offer(
            db_session,
            doc_org,
            doc_partner,
            doc_template,
            '2.00',
            min_quantity='1000',
        )

        small = _hint(client, doc_auth_headers, doc_partner, doc_template, quantity='5')
        bulk = _hint(
            client, doc_auth_headers, doc_partner, doc_template, quantity='1000'
        )
        unspecified = _hint(client, doc_auth_headers, doc_partner, doc_template)

        assert Decimal(str(small['unit_price'])) == Decimal('3')
        assert Decimal(str(bulk['unit_price'])) == Decimal('2')
        # No quantity typed yet is a line of one, not "every tier at once".
        assert Decimal(str(unspecified['unit_price'])) == Decimal('3')

    def test_an_expired_or_future_price_is_not_suggested(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        today = date.today()
        _offer(db_session, doc_org, doc_partner, doc_template, '3.00')
        _offer(
            db_session,
            doc_org,
            doc_partner,
            doc_template,
            '1.00',
            valid_from=today - timedelta(days=400),
            valid_to=today - timedelta(days=200),
        )
        _offer(
            db_session,
            doc_org,
            doc_partner,
            doc_template,
            '0.50',
            valid_from=today + timedelta(days=30),
        )

        hint = _hint(client, doc_auth_headers, doc_partner, doc_template)

        assert Decimal(str(hint['unit_price'])) == Decimal('3')
        assert hint['source'] == 'pricelist'

    def test_the_house_currency_is_preferred_to_a_lower_number_in_another(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        foreign = 'EUR' if doc_org.currency != 'EUR' else 'GBP'
        _offer(db_session, doc_org, doc_partner, doc_template, '5.00')
        _offer(db_session, doc_org, doc_partner, doc_template, '4.00', currency=foreign)

        hint = _hint(client, doc_auth_headers, doc_partner, doc_template)

        assert Decimal(str(hint['unit_price'])) == Decimal('5')
        assert hint['currency'] == doc_org.currency
