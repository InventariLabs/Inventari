"""The notice to an approver names the document, who asked and the amount.

Two receipts above the threshold gave the approver two notices with one text,
"An approval request is waiting for your decision", and only the queue could
tell them apart. The amount is net, the side the threshold is set on, and the
queue reports the same figure.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation


def _threshold_of_500(client: TestClient, headers: dict[str, str]) -> None:
    profile = client.get('/api/v1/warehouse/profile', headers=headers).json()
    put = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={
            **{
                k: v
                for k, v in profile.items()
                if k not in ('id', 'organization_id', 'created_at', 'updated_at')
            },
            'approval_threshold': '500.00',
            'approval_required_for_types': [],
            'value_tracking_enabled': True,
            'tax_handling': 'SIMPLE_RATE',
        },
    )
    assert put.status_code == status.HTTP_200_OK, put.text


def _request_with_tax(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    item: Item,
) -> dict[str, Any]:
    """A receipt of 750 net, 922.50 gross, sent to the approval queue."""
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [
                {
                    'item_id': str(item.id),
                    'expected_quantity': 10,
                    'unit_price': '75.00',
                    'tax_rate': '23',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.json()['status'] == 'PENDING_APPROVAL', confirmed.text
    document: dict[str, Any] = confirmed.json()
    assert document['total_gross'] == '922.50'
    return document


def _approver_notices(db: Session, approver_id: UUID) -> list[Notification]:
    db.expire_all()
    return list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == approver_id,
                Notification.link.like('/approvals%'),
            )
        )
    )


@pytest.mark.integration
class TestTheApproverIsToldWhatIsAsked:
    @pytest.mark.parametrize(
        ('language', 'figure', 'side'),
        [('en', '750.00', 'net'), ('pl', '750,00', 'netto')],
    )
    def test_the_notice_names_the_document_the_requester_and_the_net_amount(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: Any,
        language: str,
        figure: str,
        side: str,
    ) -> None:
        approver = h.create_user(doc_org, email='boss@example.com', role='admin')
        approver.preferred_language = language
        requester = h.create_user(doc_org, email='kamil@example.com', role='user')
        requester.full_name = 'Kamil Wrona'
        db_session.commit()
        _threshold_of_500(client, doc_auth_headers)

        document = _request_with_tax(
            client,
            h.get_auth_headers(requester),
            doc_partner,
            doc_target_location,
            doc_item,
        )

        notices = _approver_notices(db_session, approver.id)
        assert len(notices) == 1
        notice = notices[0]
        assert document['number'] in notice.title
        assert 'Kamil Wrona' in notice.content
        assert document['number'] in notice.content
        assert figure in notice.content
        assert f' {side}.' in notice.content
        assert '922' not in notice.content

    def test_the_queue_reports_the_same_net_figure(
        self,
        client: TestClient,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: Any,
    ) -> None:
        _threshold_of_500(client, doc_auth_headers)
        document = _request_with_tax(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        approval = client.get(
            f'/api/v1/approvals/documents/{document["id"]}/approval',
            headers=doc_auth_headers,
        ).json()
        assert approval['target_summary']['total_value'] == '750.00'

    def test_a_requester_or_a_number_nobody_can_name_leaves_the_plain_notice(
        self,
    ) -> None:
        from app.modules.approvals._services_notify import _RequestFacts

        facts = _RequestFacts(requester=None, number=None, amount=None, currency=None)
        assert facts.title('en') == 'New approval request'
        assert 'waiting for your decision' in facts.content('en')
