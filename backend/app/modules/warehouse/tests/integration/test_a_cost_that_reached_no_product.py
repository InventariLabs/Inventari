"""A freight bill that comes after the receipt is posted is kept, not lost.

The amount is a fact about the delivery. It is recorded with its reason and
the day it belongs to, listed and summed where a manager looks, and it is
never part of what the stock is worth: the stock-on-a-date report does not
move when one is added.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import status
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document

_TODAY = date.today()


def _posted_receipt(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 100,
                    'unit_price': '10.00',
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    doc_id = str(created.json()['id'])
    client.patch(f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers)
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == 200, done.text
    return doc_id


def _variance(
    client: TestClient, headers: dict[str, str], doc_id: str, **extra: Any
) -> Response:
    body = {
        'kind': 'freight',
        'amount': '200.00',
        'reason': 'The haulier invoiced after the goods were posted',
    }
    body.update(extra)
    return client.post(
        f'/api/v1/warehouse/documents/{doc_id}/cost-variances',
        headers=headers,
        json=body,
    )


def _stock_figures(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    on_a_date = client.get(
        '/api/v1/stock-as-of', params={'as_of': _TODAY.isoformat()}, headers=headers
    )
    assert on_a_date.status_code == 200, on_a_date.text
    return {'as_of': on_a_date.json()}


class TestRecordingAVariance:
    def test_a_posted_receipt_takes_the_amount_with_reason_currency_and_day(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        on = (_TODAY - timedelta(days=2)).isoformat()

        response = _variance(
            client, doc_auth_headers, doc_id, currency=None, occurred_on=on
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        body = response.json()
        assert len(body['variances']) == 1
        recorded = body['variances'][0]
        assert Decimal(recorded['amount']) == Decimal('200.00')
        assert recorded['reason'] == 'The haulier invoiced after the goods were posted'
        assert recorded['occurred_on'] == on
        assert Decimal(body['variance_total']) == Decimal('200.00')

    def test_the_day_defaults_to_today(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        body = _variance(client, doc_auth_headers, doc_id).json()
        assert body['variances'][0]['occurred_on'] == _TODAY.isoformat()

    def test_a_reason_is_required(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        response = _variance(client, doc_auth_headers, doc_id, reason='   ')
        assert response.status_code == 422

    def test_a_currency_other_than_the_documents_is_refused_not_converted(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        doc = db_session.get(Document, doc_id)
        assert doc is not None
        other = 'USD' if doc.currency != 'USD' else 'EUR'

        response = _variance(client, doc_auth_headers, doc_id, currency=other)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        listing = client.get(
            '/api/v1/warehouse/cost-variances', headers=doc_auth_headers
        )
        assert listing.json()['items'] == []

    def test_it_can_be_taken_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        variance_id = _variance(client, doc_auth_headers, doc_id).json()['variances'][
            0
        ]['id']

        response = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}/cost-variances/{variance_id}',
            headers=doc_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['variances'] == []


class TestItIsNeverPartOfTheStockValue:
    def test_the_reports_do_not_move_when_one_is_added(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        before = _stock_figures(client, doc_auth_headers)
        assert Decimal(before['as_of']['total_value']) == Decimal('1000.00')

        assert _variance(client, doc_auth_headers, doc_id).status_code == 201

        after = _stock_figures(client, doc_auth_headers)
        # Everything but the moment the report was generated.
        before['as_of'].pop('generated_at')
        after['as_of'].pop('generated_at')
        assert after == before


class TestWhereItIsListed:
    def test_the_list_names_the_document_and_adds_up_per_currency(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        _variance(client, doc_auth_headers, doc_id, amount='200.00')
        _variance(
            client,
            doc_auth_headers,
            doc_id,
            amount='50.50',
            kind='duty',
            occurred_on=(_TODAY - timedelta(days=30)).isoformat(),
        )

        everything = client.get(
            '/api/v1/warehouse/cost-variances', headers=doc_auth_headers
        ).json()

        assert len(everything['items']) == 2
        assert everything['items'][0]['document_number']
        assert sum(Decimal(v) for v in everything['totals'].values()) == Decimal(
            '250.50'
        )

        lately = client.get(
            '/api/v1/warehouse/cost-variances',
            params={'date_from': (_TODAY - timedelta(days=7)).isoformat()},
            headers=doc_auth_headers,
        ).json()
        assert [Decimal(item['amount']) for item in lately['items']] == [
            Decimal('200.00')
        ]
        assert sum(Decimal(v) for v in lately['totals'].values()) == Decimal('200.00')


class TestTheRefusalOffersTheChoice:
    def test_the_posted_receipt_refusal_names_the_variance(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _posted_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )

        response = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'variance' in message.lower()
