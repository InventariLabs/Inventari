"""A write-off under the approval threshold needs no approval.

A write-off asks for no price; it is worth what the cost layers it draws were
worth, which is written when it is posted. At confirmation it had no value, and
no value is over every limit: two rolls of tape worth 25 under a threshold of
500 raised an approval request, and its page then showed the approval step and
an "approved by" line for a document nobody had to approve. The threshold now
reads the cost the goods already carry.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalRequest, ApprovalWorkflow

API = '/api/v1/warehouse'


def _set_threshold(client: TestClient, headers: dict[str, str], threshold: str) -> None:
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
            'approval_threshold': threshold,
            'approval_required_for_types': [],
            'value_tracking_enabled': True,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _receive_ten(
    client: TestClient,
    headers: dict[str, str],
    shelf: StorageLocation,
    template: ProductTemplate,
    partner: Partner,
    *,
    price: str | None,
) -> str:
    line: dict[str, Any] = {
        'product_template_id': str(template.id),
        'expected_quantity': 10,
        'done_quantity': 10,
    }
    if price is not None:
        line['unit_price'] = price
    created = client.post(
        f'{API}/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [line],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id: str = created.json()['id']
    client.patch(f'{API}/documents/{doc_id}/confirm', headers=headers)
    done = client.patch(
        f'{API}/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


def _write_off_draft(
    client: TestClient,
    headers: dict[str, str],
    shelf: StorageLocation,
    item: Item,
    quantity: int,
) -> str:
    created = client.post(
        f'{API}/documents',
        headers=headers,
        json={
            'type': 'SCRAP',
            'reason_code': 'DAMAGED',
            'source_location_id': str(shelf.id),
            'lines': [{'item_id': str(item.id), 'expected_quantity': quantity}],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id: str = created.json()['id']
    return doc_id


def _requests(db: Session, doc_id: str) -> list[ApprovalRequest]:
    db.expire_all()
    return list(
        db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.target_id == doc_id,
                ApprovalRequest.target_type == 'document',
            )
        )
    )


@pytest.fixture
def stock_at_twelve_fifty(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
    db_session: Session,
    doc_approval_workflow: ApprovalWorkflow,
) -> Item:
    """Ten pieces received at 12.50, and a threshold of 100 from here on."""
    _set_threshold(client, doc_auth_headers, '100000.00')
    _receive_ten(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_template,
        doc_partner,
        price='12.50',
    )
    _set_threshold(client, doc_auth_headers, '100.00')
    return db_session.scalars(
        select(Item).where(Item.template_id == doc_template.id)
    ).one()


@pytest.mark.integration
class TestAWriteOffIsWeighedAtWhatItCosts:
    def test_under_the_threshold_it_raises_no_request_and_shows_no_trail(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        stock_at_twelve_fifty: Item,
    ) -> None:
        doc_id = _write_off_draft(
            client,
            doc_auth_headers,
            doc_target_location,
            stock_at_twelve_fifty,
            quantity=2,
        )
        # The dialog in front of the button promises what confirming does.
        requirement = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval-requirement',
            headers=doc_auth_headers,
        )
        assert requirement.json()['approval_required'] is False, requirement.text

        confirm = client.patch(
            f'{API}/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == 'CONFIRMED'
        assert _requests(db_session, doc_id) == []

        done = client.patch(
            f'{API}/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        # What the page draws the approval step and the approver from.
        detail = client.get(
            f'{API}/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        assert detail['approval'] is None
        assert _requests(db_session, doc_id) == []
        assert (
            db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == doc_org.id,
                    AuditLog.target_type == 'approval_request',
                )
            ).all()
            == []
        )

    def test_over_the_threshold_it_waits_for_the_approval(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        stock_at_twelve_fifty: Item,
    ) -> None:
        doc_id = _write_off_draft(
            client,
            doc_auth_headers,
            doc_target_location,
            stock_at_twelve_fifty,
            quantity=9,
        )
        confirm = client.patch(
            f'{API}/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.json()['status'] == 'PENDING_APPROVAL', confirm.text
        assert len(_requests(db_session, doc_id)) == 1

    def test_goods_with_no_cost_cannot_be_shown_to_be_under_the_limit(
        self,
        client: TestClient,
        db_session: Session,
        request: pytest.FixtureRequest,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        # Received before any control existed, with no price on it.
        _receive_ten(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_template,
            doc_partner,
            price=None,
        )
        request.getfixturevalue('doc_approval_workflow')
        _set_threshold(client, doc_auth_headers, '100.00')
        item = db_session.scalars(
            select(Item).where(Item.template_id == doc_template.id)
        ).one()

        doc_id = _write_off_draft(
            client, doc_auth_headers, doc_target_location, item, quantity=1
        )
        confirm = client.patch(
            f'{API}/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.json()['status'] == 'PENDING_APPROVAL', confirm.text

    def test_a_correction_under_the_threshold_raises_no_request(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        _set_threshold(client, doc_auth_headers, '100000.00')
        receipt_id = _receive_ten(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_template,
            doc_partner,
            price='12.50',
        )
        _set_threshold(client, doc_auth_headers, '500.00')
        receipt = client.get(
            f'{API}/documents/{receipt_id}', headers=doc_auth_headers
        ).json()
        created = client.post(
            f'{API}/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': receipt_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': receipt['lines'][0]['line_number'],
                        'quantity_delta': -8,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        correction_id: str = created.json()['id']
        applied = client.patch(
            f'{API}/documents/{correction_id}/confirm', headers=doc_auth_headers
        )
        assert applied.status_code == status.HTTP_200_OK, applied.text
        assert applied.json()['status'] == 'CONFIRMED'
        assert _requests(db_session, correction_id) == []
