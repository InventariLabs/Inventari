"""The last-purchase price hint is what was last paid, and only a purchase asks for it.

A product received at 8.00 and then delivered to a customer at 10.00 must
hint 8.00 on the next receipt: the delivery's price is what the customer
paid, not what the goods cost. A delivery form itself is offered no
purchase price at all — neither the last receipt's nor a supplier's offer
— only the rate of tax.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.purchase_orders.models import PartnerPricelist
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus

_START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


@pytest.fixture
def doc_org(h: ModuleTestHelper, db_session: Session) -> Organization:
    """Purchasing on, so a supplier's offer is there to be offered; Polish,
    so the full-value profile answers a rate of tax."""
    org = h.create_org(
        'Last Price Org',
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
    org.country = 'PL'
    db_session.commit()
    return org


def _posted(
    db: Session,
    org: Organization,
    user: User,
    template: ProductTemplate,
    doc_type: str,
    price: str,
    day: int,
    *,
    corrects_line_id: UUID | None = None,
) -> UUID:
    """A completed document of *doc_type* with one line priced at *price*.

    ``day`` orders the documents: the hint reads the newest one.
    """
    doc = Document(
        organization_id=org.id,
        type=doc_type,
        number=f'{doc_type}/{uuid4().hex[:8]}',
        status=DocumentStatus.COMPLETED.value,
        created_by=user.id,
        currency=org.currency,
        created_at=_START + timedelta(days=day),
    )
    line = DocumentLine(
        line_number=1,
        product_template_id=template.id,
        quantity=Decimal('5'),
        expected_quantity=Decimal('5'),
        done_quantity=Decimal('5'),
        unit_price=Decimal(price),
        corrects_line_id=corrects_line_id,
    )
    doc.lines.append(line)
    db.add(doc)
    db.commit()
    return line.id


def _hint(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    **params: str,
) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/price-hint',
        headers=headers,
        params={'template_id': str(template.id), **params},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.integration
class TestThePriceHintReadsWhatWasPaid:
    @pytest.mark.parametrize(
        'later_type',
        ['OUT', 'INTERNAL_OUT', 'INT', 'CORRECTION', 'SCRAP', 'ADJUSTMENT'],
    )
    def test_a_later_document_that_is_not_a_receipt_is_not_the_last_purchase(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_template: ProductTemplate,
        db_session: Session,
        later_type: str,
    ) -> None:
        _posted(db_session, doc_org, doc_user, doc_template, 'IN', '8.00', day=0)
        _posted(db_session, doc_org, doc_user, doc_template, 'IN', '8.00', day=1)
        _posted(db_session, doc_org, doc_user, doc_template, later_type, '10.00', day=2)

        hint = _hint(client, doc_auth_headers, doc_template, document_type='IN')

        assert Decimal(str(hint['unit_price'])) == Decimal('8')
        assert hint['source'] == 'last_purchase'

    def test_goods_a_customer_returns_come_back_at_the_sale_price_not_a_purchase(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A delivery's return is a receipt carrying the delivery's price."""
        _posted(db_session, doc_org, doc_user, doc_template, 'IN', '8.00', day=0)
        delivered = _posted(
            db_session, doc_org, doc_user, doc_template, 'OUT', '10.00', day=1
        )
        _posted(
            db_session,
            doc_org,
            doc_user,
            doc_template,
            'IN',
            '10.00',
            day=2,
            corrects_line_id=delivered,
        )

        hint = _hint(client, doc_auth_headers, doc_template, document_type='IN')

        assert Decimal(str(hint['unit_price'])) == Decimal('8')

    def test_an_internal_receipt_is_a_receipt(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        _posted(db_session, doc_org, doc_user, doc_template, 'IN', '8.00', day=0)
        _posted(
            db_session, doc_org, doc_user, doc_template, 'INTERNAL_IN', '9.00', day=1
        )

        hint = _hint(client, doc_auth_headers, doc_template, document_type='IN')

        assert Decimal(str(hint['unit_price'])) == Decimal('9')
        assert hint['source'] == 'last_purchase'

    @pytest.mark.parametrize('delivery', ['OUT', 'WZ'])
    def test_a_delivery_is_offered_the_rate_of_tax_and_no_purchase_price(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
        delivery: str,
    ) -> None:
        """Neither what was paid nor a supplier's offer is a sale price."""
        applied = client.post(
            '/api/v1/warehouse/profile/apply-preset/Full Value',
            headers=doc_auth_headers,
        )
        assert applied.status_code == status.HTTP_200_OK, applied.text
        _posted(db_session, doc_org, doc_user, doc_template, 'IN', '8.00', day=0)
        db_session.add(
            PartnerPricelist(
                organization_id=doc_org.id,
                partner_id=doc_partner.id,
                product_template_id=doc_template.id,
                unit_price=Decimal('7.00'),
                currency=doc_org.currency,
                valid_from=_START.date() - timedelta(days=30),
            )
        )
        db_session.commit()
        partner = {'partner_id': str(doc_partner.id)}

        receipt = _hint(
            client, doc_auth_headers, doc_template, document_type='IN', **partner
        )
        dispatch = _hint(
            client, doc_auth_headers, doc_template, document_type=delivery, **partner
        )

        assert Decimal(str(receipt['unit_price'])) == Decimal('7')
        assert dispatch['unit_price'] is None
        assert dispatch['source'] is None
        assert dispatch['currency'] is None
        assert dispatch['tax_rate'] == receipt['tax_rate'] == '23.00'
