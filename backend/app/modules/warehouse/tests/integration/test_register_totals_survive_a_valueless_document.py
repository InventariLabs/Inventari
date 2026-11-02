"""One priceless document must not cost the register its totals.

The register buckets by currency and refuses to add two of them together. A
document with no currency landed in a bucket of its own, so a month of eleven
USD receipts plus one correction read as multi-currency and came back with
null net, tax and gross — an em dash on the one screen whose whole job is to
prove the amounts. The correction had no currency because that document type
was built by hand, without the header field and without the value pass every
other type runs.
"""

import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document


def _enable_value_tracking(client: TestClient, headers: dict[str, str]) -> None:
    profile = client.get('/api/v1/warehouse/profile', headers=headers).json()
    resp = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={
            **{
                k: v
                for k, v in profile.items()
                if k not in ('id', 'organization_id', 'created_at', 'updated_at')
            },
            'value_tracking_enabled': True,
        },
    )
    assert resp.status_code == 200, resp.text


def _priced_receipt(
    client: TestClient,
    headers: dict[str, str],
    target_location_id: uuid.UUID,
    template_id: uuid.UUID,
    partner_id: uuid.UUID,
    quantity: int = 2,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'done_quantity': quantity,
                    'unit_price': '10.00',
                    'tax_rate': '23.00',
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    doc_id: str = resp.json()['id']
    client.patch(f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers)
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == 200, done.text
    return doc_id


def _register(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    today = date.today()
    resp = client.get(
        f'/api/v1/warehouse/register/summary?date_from={today}&date_to={today}',
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


@pytest.mark.integration
class TestValuelessDocumentIsNotACurrency:
    def test_a_document_with_no_value_leaves_the_usd_total_standing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        _enable_value_tracking(client, doc_auth_headers)
        priced_id = _priced_receipt(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )

        # A document with neither a currency nor a price — the shape the
        # correction service used to produce.
        bare = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                        'done_quantity': 1,
                    }
                ],
            },
        )
        assert bare.status_code == 201, bare.text
        bare_id = bare.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{bare_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{bare_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        bare_doc = db_session.scalars(
            select(Document).where(Document.id == uuid.UUID(bare_id))
        ).first()
        assert bare_doc is not None
        bare_doc.currency = None
        bare_doc.total_net = None
        bare_doc.total_tax = None
        bare_doc.total_gross = None
        db_session.commit()

        data = _register(client, doc_auth_headers)
        summary = data['summary']

        assert len(summary['totals_by_currency']) == 1
        assert summary['total_net'] == '20.00'
        assert summary['total_tax'] == '4.60'
        assert summary['total_gross'] == '24.60'
        assert summary['currency'] is not None

        # And both documents are still in the register — nothing was dropped
        # to make the sum work. The rows endpoint serves the group's page.
        rows = client.get(
            f'/api/v1/warehouse/register/rows'
            f'?date_from={date.today()}&date_to={date.today()}'
            f'&group_by=type&group_key=IN',
            headers=doc_auth_headers,
        )
        assert rows.status_code == 200, rows.text
        listed = {doc['id'] for doc in rows.json()['items']}
        assert priced_id in listed
        assert bare_id in listed


@pytest.mark.integration
class TestACorrectionCarriesItsMoney:
    def test_a_correction_inherits_the_currency_and_values_of_what_it_corrects(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        db_session: Session,
    ) -> None:
        _enable_value_tracking(client, doc_auth_headers)
        original_id = _priced_receipt(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
            quantity=2,
        )
        original = db_session.scalars(
            select(Document).where(Document.id == uuid.UUID(original_id))
        ).first()
        assert original is not None
        assert original.currency is not None

        resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original_id,
                'lines': [{'original_line_number': 1, 'quantity_delta': '-1'}],
                'reason_code': 'WRONG_QUANTITY',
            },
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()

        assert body['currency'] == original.currency
        # One unit off a 10.00 line at 23%: net -10.00, tax -2.30, gross -12.30.
        assert body['total_net'] == '-10.00'
        assert body['total_tax'] == '-2.30'
        assert body['total_gross'] == '-12.30'


@pytest.mark.integration
class TestTheWindowSummaryAddsTheGroupsOfOneCurrency:
    def test_two_groups_of_one_currency_sum_into_one_bucket(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        h: Any,
        doc_org: Any,
        doc_user: Any,
        db_session: Session,
    ) -> None:
        """The window summary answers per currency, not per group.

        The SQL groups by (group, currency), so a register grouped by
        partner carries one tuple per partner for the same currency. The
        fold used to pass those through untouched: two partners of PLN
        gave the summary two PLN buckets, the stacked totals rendered two
        children keyed "PLN" — React's duplicate-key warning — and the
        window's own total read as two parallel amounts instead of one.
        """
        _enable_value_tracking(client, doc_auth_headers)
        _priced_receipt(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            doc_partner.id,
        )
        second = h.create_partner(doc_org, doc_user, name='Baltic Goods')
        _priced_receipt(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_template.id,
            second.id,
        )

        today = date.today()
        resp = client.get(
            f'/api/v1/warehouse/register/summary'
            f'?date_from={today}&date_to={today}&group_by=partner',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data: dict[str, Any] = resp.json()

        assert len(data['groups']) == 2
        summary = data['summary']
        assert len(summary['totals_by_currency']) == 1
        assert summary['total_net'] == '40.00'
        assert summary['total_tax'] == '9.20'
        assert summary['total_gross'] == '49.20'
        assert summary['currency'] is not None
