"""A delivery line nobody priced does not become a stated cost by being shipped.

Freight, duty and insurance are spread over the lines of a delivery. A line
with a price carries it plus its share, and the layer says the cost was
stated. A line with *no* price used to be posted as a stated cost worth only
its share of the freight: two a piece on a hundred-unit line, filed as what
the supplier charged, beside an average cost of ten that the same shelf
would have been valued at had the freight never been booked. The layer model
says an unpriced line keeps the basis an unpriced line has - average where
the organization has a rate, unknown where it has none - and the freight rides
on top of that.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation


def _deliver(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    *,
    price: str | None,
    freight: str | None = None,
) -> str:
    line: dict[str, str | int] = {
        'product_template_id': str(template.id),
        'expected_quantity': 100,
    }
    if price is not None:
        line['unit_price'] = price
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [line],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = str(created.json()['id'])
    if freight is not None:
        added = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=headers,
            json={'kind': 'freight', 'amount': freight},
        )
        assert added.status_code == status.HTTP_201_CREATED, added.text
    client.patch(f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers)
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


def _layers(db: Session, template: ProductTemplate) -> list[StockValuationLayer]:
    db.expire_all()
    return list(
        db.scalars(
            select(StockValuationLayer)
            .where(
                StockValuationLayer.product_template_id == template.id,
                StockValuationLayer.direction == 'IN',
            )
            .order_by(StockValuationLayer.created_at)
        )
    )


class TestAPricelessLineWithFreight:
    def test_with_no_rate_on_the_books_the_layer_stays_unknown(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _deliver(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            doc_template,
            price=None,
            freight='200.00',
        )

        (layer,) = _layers(db_session, doc_template)
        assert layer.cost_basis == 'unknown'

    def test_with_a_rate_on_the_books_the_freight_rides_on_the_average(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _deliver(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            doc_template,
            price='10.00',
        )
        _deliver(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            doc_template,
            price=None,
            freight='200.00',
        )

        _priced, unpriced = _layers(db_session, doc_template)
        assert unpriced.cost_basis == 'average'
        # The average of ten, and two of freight on each unit.
        assert Decimal(unpriced.unit_cost) == Decimal('12.00')

    def test_a_priced_line_with_freight_is_still_stated(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _deliver(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            doc_template,
            price='10.00',
            freight='200.00',
        )

        (layer,) = _layers(db_session, doc_template)
        assert layer.cost_basis == 'stated'
        assert Decimal(layer.unit_cost) == Decimal('12.00')
