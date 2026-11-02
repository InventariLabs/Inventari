"""Completing a dispatch can record its hand-over to a carrier.

The shipment rides the completion's transaction: it exists exactly when the
stock left, it belongs to dispatches only, and it is read back with the
document — with a tracking link where the carrier has a template — and
announced as ``document.shipped``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.contracts.events import DocumentShippedPayload
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse import _document_workflow_transitions as transitions
from app.modules.warehouse.models import (
    Document,
    DocumentDiscrepancyCode,
    DocumentPackage,
    DocumentShipment,
    DocumentStatus,
)
from app.modules.webhooks.schemas import valid_event_types

pytestmark = pytest.mark.integration

_DOCS = '/api/v1/warehouse/documents'
_MODULE = '/api/v1/warehouse'


def _confirmed_dispatch(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    shelf: StorageLocation,
    stock: Item,
    template: ProductTemplate,
    quantity: int = 5,
) -> str:
    created = client.post(
        _DOCS,
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(shelf.id),
            'lines': [
                {
                    'item_id': str(stock.id),
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id: str = created.json()['id']
    confirmed = client.patch(f'{_DOCS}/{doc_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return doc_id


@pytest.fixture
def dispatch_id(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_source_location: StorageLocation,
    doc_stock_item: Item,
    doc_template: ProductTemplate,
) -> str:
    return _confirmed_dispatch(
        client,
        doc_auth_headers,
        partner=doc_partner,
        shelf=doc_source_location,
        stock=doc_stock_item,
        template=doc_template,
    )


def _shipments(db_session: Session, doc_id: str) -> int:
    db_session.expire_all()
    count = db_session.scalar(
        select(func.count())
        .select_from(DocumentShipment)
        .where(DocumentShipment.document_id == UUID(doc_id))
    )
    assert count is not None
    return count


class TestADispatchShipsOnCompletion:
    def test_completion_records_the_shipment_with_its_tracking_link(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_user: User,
        dispatch_id: str,
    ) -> None:
        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={
                'complete_as_planned': True,
                'shipment': {
                    'carrier': ' InPost ',
                    'tracking_number': '6200 1234',
                    'notes': 'Courier at gate 2',
                },
            },
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        assert done.json()['status'] == DocumentStatus.COMPLETED.value
        shipment = done.json()['shipment']
        assert shipment['carrier'] == 'InPost'
        assert shipment['tracking_number'] == '6200 1234'
        assert shipment['tracking_url'] == (
            'https://inpost.pl/sledzenie-przesylek?number=6200%201234'
        )
        assert shipment['shipped_by'] == str(doc_user.id)
        assert shipment['shipped_by_name'] == (doc_user.full_name or doc_user.email)
        assert shipment['shipped_at'] is not None
        assert shipment['notes'] == 'Courier at gate 2'
        assert shipment['package_count'] == 0

        read = client.get(f'{_DOCS}/{dispatch_id}', headers=doc_auth_headers)
        assert read.json()['shipment'] == shipment
        listed = client.get(
            _DOCS, headers=doc_auth_headers, params={'type': 'OUT'}
        ).json()['items']
        assert [d['shipment'] for d in listed if d['id'] == dispatch_id] == [shipment]

    def test_the_by_number_read_carries_the_shipment(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        dispatch_id: str,
    ) -> None:
        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={
                'complete_as_planned': True,
                'shipment': {'carrier': 'InPost', 'tracking_number': '6200 1234'},
            },
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        shipment = done.json()['shipment']
        number = done.json()['number']

        by_number = client.get(f'{_DOCS}/lookup/{number}', headers=doc_auth_headers)

        assert by_number.status_code == status.HTTP_200_OK, by_number.text
        assert by_number.json()['shipment'] == shipment

    def test_shipped_event_carries_number_carrier_tracking_and_packages(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        dispatch_id: str,
    ) -> None:
        for number in (1, 2):
            db_session.add(
                DocumentPackage(
                    organization_id=doc_org.id,
                    document_id=UUID(dispatch_id),
                    number=number,
                )
            )
        db_session.commit()
        received: list[Any] = []
        core_api.events.subscribe('document.shipped', received.append)

        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={
                'complete_as_planned': True,
                'shipment': {'carrier': 'DPD', 'tracking_number': 'X1'},
            },
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        assert len(received) == 1
        event = received[0]
        assert isinstance(event, DocumentShippedPayload)
        assert event.organization_id == str(doc_org.id)
        assert event.document_id == dispatch_id
        assert event.document_number == done.json()['number']
        assert event.document_type == 'OUT'
        assert event.carrier == 'DPD'
        assert event.tracking_number == 'X1'
        assert event.tracking_url == (
            'https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1=X1'
        )
        assert event.package_count == 2
        assert done.json()['shipment']['package_count'] == 2

    def test_completion_without_a_shipment_records_none_and_announces_none(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        dispatch_id: str,
    ) -> None:
        received: list[Any] = []
        core_api.events.subscribe('document.shipped', received.append)

        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        assert done.json()['shipment'] is None
        assert _shipments(db_session, dispatch_id) == 0
        assert received == []

    def test_a_posting_failure_leaves_no_shipment(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
        dispatch_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The stock posts and then the posting step fails: everything the
        # completion wrote — the stock and the shipment ahead of it — goes.
        post = transitions.execute_stock_operations

        async def post_then_fail(*args: Any, **kwargs: Any) -> None:
            await post(*args, **kwargs)
            raise ValueError('the posting failed')

        monkeypatch.setattr(transitions, 'execute_stock_operations', post_then_fail)

        refused = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={
                'complete_as_planned': True,
                'shipment': {'carrier': 'UPS', 'tracking_number': '1Z999'},
            },
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert _shipments(db_session, dispatch_id) == 0
        doc = db_session.get(Document, UUID(dispatch_id))
        assert doc is not None
        assert doc.status == DocumentStatus.CONFIRMED.value
        db_session.refresh(doc_stock_item)
        assert doc_stock_item.quantity == Decimal('100')

    def test_a_shipment_alone_keeps_the_shortfall_a_session_wrote(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
        dispatch_id: str,
    ) -> None:
        # A picking session wrote 3 of 5 and why; the page closing it sends
        # the hand-over and no lines. The shipment must not answer for the
        # lines: they book what was picked, as a completion with no body does.
        doc = db_session.get(Document, UUID(dispatch_id))
        assert doc is not None
        line = doc.lines[0]
        line.done_quantity = Decimal('3')
        line.discrepancy_code = DocumentDiscrepancyCode.SHORTAGE.value
        db_session.commit()

        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={'shipment': {'carrier': 'DPD', 'tracking_number': 'X2'}},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        assert Decimal(str(done.json()['lines'][0]['done_quantity'])) == Decimal('3')
        db_session.refresh(doc_stock_item)
        assert doc_stock_item.quantity == Decimal('97')

    def test_a_receipt_refuses_a_shipment_and_stays_open(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        created = client.post(
            _DOCS,
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        doc_id = created.json()['id']
        client.patch(f'{_DOCS}/{doc_id}/confirm', headers=doc_auth_headers)

        refused = client.patch(
            f'{_DOCS}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'shipment': {'carrier': 'DHL'}},
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert refused.json()['detail']['message'] == (
            'Only a dispatch records a shipment: a carrier takes goods that '
            'leave the warehouse.'
        )
        assert _shipments(db_session, doc_id) == 0
        doc = db_session.get(Document, UUID(doc_id))
        assert doc is not None
        assert doc.status == DocumentStatus.CONFIRMED.value

    def test_a_blank_carrier_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        dispatch_id: str,
    ) -> None:
        refused = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={'shipment': {'carrier': '   ', 'tracking_number': '1'}},
        )

        assert refused.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert _shipments(db_session, dispatch_id) == 0

    def test_webhooks_offer_the_shipment_as_a_topic_of_its_own(self) -> None:
        assert 'document.shipped' in valid_event_types()


class TestTrackingLinksAndCarriers:
    def test_an_organization_template_links_its_own_carrier(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        dispatch_id: str,
    ) -> None:
        saved = client.put(
            f'{_MODULE}/profile',
            headers=doc_auth_headers,
            json={
                'tracking_url_templates': {
                    'Raben': 'https://raben.example/track/{tracking_number}'
                }
            },
        )
        assert saved.status_code == status.HTTP_200_OK, saved.text
        assert saved.json()['tracking_url_templates'] == {
            'Raben': 'https://raben.example/track/{tracking_number}'
        }

        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={
                'complete_as_planned': True,
                'shipment': {'carrier': 'raben', 'tracking_number': 'R/42'},
            },
        )

        assert done.json()['shipment']['tracking_url'] == (
            'https://raben.example/track/R%2F42'
        )

    def test_an_unknown_carrier_shows_the_plain_number(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        dispatch_id: str,
    ) -> None:
        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={
                'complete_as_planned': True,
                'shipment': {'carrier': 'Our van', 'tracking_number': 'V-7'},
            },
        )

        shipment = done.json()['shipment']
        assert shipment['tracking_number'] == 'V-7'
        assert shipment['tracking_url'] is None

    def test_a_template_without_the_number_is_refused_in_the_readers_language(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        refused = client.put(
            f'{_MODULE}/profile',
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            json={'tracking_url_templates': {'Raben': 'https://raben.example/'}},
        )

        assert refused.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert refused.json()['detail'][0]['msg'] == (
            'Link do śledzenia dla „Raben” musi być adresem strony zaczynającym '
            'się od https:// lub http:// i zawierać {tracking_number} w miejscu '
            'numeru.'
        )

    def test_carriers_are_suggested_from_this_organization_latest_first(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        other = h.create_org('Other Shipping Org', ['core', 'warehouse'])
        other_user = h.create_user(other, email='other-shipper@example.com')

        def ship(org: Organization, user: User, carrier: str, day: int) -> None:
            doc = Document(
                organization_id=org.id,
                type='OUT',
                number=f'OUT/{org.name}/{day}',
                status=DocumentStatus.COMPLETED.value,
                created_by=user.id,
            )
            db_session.add(doc)
            db_session.flush()
            db_session.add(
                DocumentShipment(
                    organization_id=org.id,
                    document_id=doc.id,
                    carrier=carrier,
                    shipped_at=f'2026-10-{day:02d}T12:00:00+00:00',
                    shipped_by=user.id,
                )
            )

        ship(doc_org, doc_user, 'dhl', 1)
        ship(doc_org, doc_user, 'InPost', 2)
        ship(doc_org, doc_user, 'DHL', 3)
        ship(other, other_user, 'Raben', 4)
        db_session.commit()

        answer = client.get(f'{_MODULE}/shipments/carriers', headers=doc_auth_headers)

        assert answer.status_code == status.HTTP_200_OK, answer.text
        assert answer.json() == {'carriers': ['DHL', 'InPost']}


class TestTheRegisterCarriesShipments:
    """The register is where a shipped dispatch is looked up a month later.

    The rows endpoint was the one read of a document that did not carry the
    hand-over, so the register had no column to show. The window's summary
    says whether anything in it shipped at all, which is what tells the
    screen to offer the columns or leave them out.
    """

    def _rows(
        self,
        client: TestClient,
        headers: dict[str, str],
        group_key: str,
    ) -> dict[str, Any]:
        today = date.today().isoformat()
        answer = client.get(
            f'{_MODULE}/register/rows',
            headers=headers,
            params={
                'date_from': today,
                'date_to': today,
                'group_key': group_key,
            },
        )
        assert answer.status_code == status.HTTP_200_OK, answer.text
        rows: dict[str, Any] = answer.json()
        return rows

    def test_a_shipped_row_carries_carrier_tracking_and_link(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        dispatch_id: str,
    ) -> None:
        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={
                'complete_as_planned': True,
                'shipment': {'carrier': 'InPost', 'tracking_number': '6200'},
            },
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        today = date.today().isoformat()
        summary = client.get(
            f'{_MODULE}/register/summary',
            headers=doc_auth_headers,
            params={'date_from': today, 'date_to': today},
        )
        assert summary.status_code == status.HTTP_200_OK, summary.text
        assert summary.json()['summary']['has_shipments'] is True

        row = next(
            row
            for row in self._rows(client, doc_auth_headers, 'OUT')['items']
            if row['id'] == dispatch_id
        )
        assert row['carrier'] == 'InPost'
        assert row['tracking_number'] == '6200'
        assert row['tracking_url'] == (
            'https://inpost.pl/sledzenie-przesylek?number=6200'
        )

    def test_a_window_with_nothing_shipped_says_so(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        dispatch_id: str,
    ) -> None:
        done = client.patch(
            f'{_DOCS}/{dispatch_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        today = date.today().isoformat()
        summary = client.get(
            f'{_MODULE}/register/summary',
            headers=doc_auth_headers,
            params={'date_from': today, 'date_to': today},
        )
        assert summary.status_code == status.HTTP_200_OK, summary.text
        assert summary.json()['summary']['has_shipments'] is False

        row = next(
            row
            for row in self._rows(client, doc_auth_headers, 'OUT')['items']
            if row['id'] == dispatch_id
        )
        assert row['carrier'] is None
        assert row['tracking_number'] is None
        assert row['tracking_url'] is None
