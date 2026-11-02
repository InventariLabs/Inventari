"""A write-off says why, and what it cost.

A scrapped pair of boxes used to leave the register as a row with a count and
no amount: the loss was in no total, and nothing on the document said whether
the goods were damaged or simply out of date.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

API = '/api/v1/warehouse'


def _enable_value_tracking(client: TestClient, headers: dict[str, str]) -> None:
    profile = client.get(f'{API}/profile', headers=headers).json()
    resp = client.put(
        f'{API}/profile',
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


def _post(client: TestClient, headers: dict[str, str], body: dict[str, Any]) -> str:
    created = client.post(f'{API}/documents', headers=headers, json=body)
    assert created.status_code == 201, created.text
    doc_id: str = created.json()['id']
    client.patch(f'{API}/documents/{doc_id}/confirm', headers=headers)
    done = client.patch(
        f'{API}/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == 200, done.text
    return doc_id


def _receive(
    client: TestClient,
    headers: dict[str, str],
    shelf: StorageLocation,
    template: ProductTemplate,
    partner: Partner,
    price: str | None,
) -> str:
    line: dict[str, Any] = {
        'product_template_id': str(template.id),
        'expected_quantity': 10,
        'done_quantity': 10,
    }
    if price is not None:
        line['unit_price'] = price
    return _post(
        client,
        headers,
        {
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [line],
        },
    )


def _scrap_body(item: Item, shelf: StorageLocation, **extra: Any) -> dict[str, Any]:
    return {
        'type': 'SCRAP',
        'source_location_id': str(shelf.id),
        'lines': [{'item_id': str(item.id), 'expected_quantity': 2}],
        **extra,
    }


@pytest.fixture
def received_item(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
    db_session: Session,
) -> Item:
    _enable_value_tracking(client, doc_auth_headers)
    _receive(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_template,
        doc_partner,
        '12.50',
    )
    return db_session.scalars(
        select(Item).where(Item.template_id == doc_template.id)
    ).one()


@pytest.mark.integration
class TestScrapValue:
    def test_a_write_off_is_worth_the_cost_layers_it_drew(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        doc_id = _post(
            client,
            doc_auth_headers,
            _scrap_body(received_item, doc_target_location, reason_code='DAMAGED'),
        )

        doc = client.get(f'{API}/documents/{doc_id}', headers=doc_auth_headers).json()
        assert doc['reason_code'] == 'DAMAGED'
        assert Decimal(doc['total_net']) == Decimal('25.00')
        assert Decimal(doc['lines'][0]['line_value']) == Decimal('25.00')

    def test_the_register_row_and_the_month_say_scrap_is_in_the_total(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        _post(
            client,
            doc_auth_headers,
            _scrap_body(received_item, doc_target_location, reason_code='EXPIRED'),
        )

        today = date.today()
        summary = client.get(
            f'{API}/register/summary?date_from={today}&date_to={today}',
            headers=doc_auth_headers,
        ).json()
        scrap = next(g for g in summary['groups'] if g['key'] == 'SCRAP')
        assert Decimal(scrap['total_net']) == Decimal('25.00')
        assert summary['summary']['scrap_documents'] == 1


@pytest.mark.integration
class TestScrapReason:
    def test_a_reason_outside_the_list_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        resp = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json=_scrap_body(received_item, doc_target_location, reason_code='BORED'),
        )
        assert resp.status_code == 422

    def test_a_receipt_takes_no_scrap_reason(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        resp = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert resp.status_code == 400

    def test_a_receipt_draft_cannot_be_given_one_either(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        created = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        ).json()
        resp = client.put(
            f'{API}/documents/{created["id"]}',
            headers=doc_auth_headers,
            json={'reason_code': 'DAMAGED'},
        )
        assert resp.status_code == 400

    def test_a_scrap_draft_can_change_its_reason(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        created = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json=_scrap_body(received_item, doc_target_location, reason_code='DAMAGED'),
        ).json()
        updated = client.put(
            f'{API}/documents/{created["id"]}',
            headers=doc_auth_headers,
            json={'reason_code': 'EXPIRED'},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()['reason_code'] == 'EXPIRED'


@pytest.mark.integration
class TestAScrapAlwaysSaysWhy:
    """The form asks for the reason; a script, a phone flow or another module
    posting the document is asked the same, or the month-end grouping by
    reason has a row it cannot place."""

    def test_a_scrap_with_no_reason_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        resp = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json=_scrap_body(received_item, doc_target_location),
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()['detail']['code'] == 'DOCUMENT_SCRAP_REASON_REQUIRED'

    def test_other_is_a_reason_only_with_a_note(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        bare = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json=_scrap_body(
                received_item, doc_target_location, reason_code='OTHER', notes='  '
            ),
        )
        noted = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json=_scrap_body(
                received_item,
                doc_target_location,
                reason_code='OTHER',
                notes='Dropped by the forklift',
            ),
        )
        assert bare.status_code == 400, bare.text
        assert noted.status_code == 201, noted.text

    def test_a_draft_cannot_clear_its_reason(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        created = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json=_scrap_body(received_item, doc_target_location, reason_code='DAMAGED'),
        ).json()
        resp = client.put(
            f'{API}/documents/{created["id"]}',
            headers=doc_auth_headers,
            json={'reason_code': None},
        )
        assert resp.status_code == 400, resp.text
        doc = client.get(
            f'{API}/documents/{created["id"]}', headers=doc_auth_headers
        ).json()
        assert doc['reason_code'] == 'DAMAGED'

    def test_a_draft_under_other_cannot_clear_its_note(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        created = client.post(
            f'{API}/documents',
            headers=doc_auth_headers,
            json=_scrap_body(
                received_item,
                doc_target_location,
                reason_code='OTHER',
                notes='Dropped by the forklift',
            ),
        ).json()
        resp = client.put(
            f'{API}/documents/{created["id"]}',
            headers=doc_auth_headers,
            json={'notes': None},
        )
        assert resp.status_code == 400, resp.text

    def test_a_copy_keeps_the_reason(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        received_item: Item,
    ) -> None:
        doc_id = _post(
            client,
            doc_auth_headers,
            _scrap_body(received_item, doc_target_location, reason_code='QUALITY'),
        )
        copy = client.post(
            f'{API}/documents/{doc_id}/duplicate', headers=doc_auth_headers
        )
        assert copy.status_code == 201, copy.text
        assert copy.json()['reason_code'] == 'QUALITY'


@pytest.mark.integration
class TestDocumentsWithoutValue:
    def test_the_register_counts_a_receipt_posted_without_a_price(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        _enable_value_tracking(client, doc_auth_headers)
        _receive(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_template,
            doc_partner,
            '12.50',
        )
        _receive(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_template,
            doc_partner,
            None,
        )

        today = date.today()
        summary = client.get(
            f'{API}/register/summary?date_from={today}&date_to={today}',
            headers=doc_auth_headers,
        ).json()['summary']
        assert summary['total_documents'] == 2
        assert Decimal(summary['total_net']) == Decimal('125.00')
        assert summary['documents_without_value'] == 1

    def test_a_profile_that_tracks_no_value_counts_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        _receive(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_template,
            doc_partner,
            None,
        )
        today = date.today()
        summary = client.get(
            f'{API}/register/summary?date_from={today}&date_to={today}',
            headers=doc_auth_headers,
        ).json()['summary']
        assert summary['documents_without_value'] == 0
