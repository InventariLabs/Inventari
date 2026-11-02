"""The one-step action posts a document whole, or writes nothing.

"Przyjmij na stan / Wydaj / Przenieś" is one press: the draft is confirmed
and completed in one transaction, through the same service functions the
step-by-step doors use. These tests hold the two promises that make the
button honest — everything the movement needs is enforced, and a refusal at
any point leaves the draft exactly as it was — and the third: where an
approval stands in the way, the approval itself finishes the posting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.public_api import core_api
from app.models.item import Item
from app.models.partner import Partner
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalRequest, ApprovalWorkflow
from app.modules.warehouse.models import Document, DocumentStatus


def _dispatch_payload(
    *,
    partner_id: Partner,
    source_location_id: StorageLocation,
    item: Item,
    quantity: int,
) -> dict[str, Any]:
    return {
        'type': 'OUT',
        'partner_id': str(partner_id.id),
        'source_location_id': str(source_location_id.id),
        'lines': [
            {
                'item_id': str(item.id),
                'product_template_id': str(item.template_id),
                'expected_quantity': quantity,
                'unit_price': '10.00',
            }
        ],
    }


def _set_threshold(client: TestClient, headers: dict[str, str], threshold: str) -> None:
    profile = client.get('/api/v1/warehouse/profile', headers=headers).json()
    cleaned = {
        k: v
        for k, v in profile.items()
        if k not in ('id', 'organization_id', 'created_at', 'updated_at')
    }
    resp = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={
            **cleaned,
            'approval_threshold': threshold,
            'approval_required_for_types': [],
            'value_tracking_enabled': True,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.fixture
def approver_notices(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the approvers were told from outside the database.

    The e-mail queue and the real-time push both leave the transaction that
    raised the request: a rollback cannot call either back. Recorded here
    rather than sent, so a test can tell whether they went out.
    """
    sent: list[str] = []

    async def fake_send(to_email: str, *_args: Any, **_kwargs: Any) -> bool:
        sent.append(f'mail:{to_email}')
        return True

    async def fake_publish(_db: Any, notifications: Any) -> None:
        if notifications:
            sent.append('push')

    monkeypatch.setattr(core_api.email, 'send_async', fake_send)
    monkeypatch.setattr(core_api.notifications, 'publish_async', fake_publish)
    return sent


@pytest.mark.integration
class TestTheOneStepActionPostsWhole:
    def test_a_draft_is_confirmed_completed_and_moved_in_one_call(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json=_dispatch_payload(
                partner_id=doc_partner,
                source_location_id=doc_source_location,
                item=doc_stock_item,
                quantity=5,
            ),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])

        posted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )
        assert posted.status_code == status.HTTP_200_OK, posted.text
        body = posted.json()
        assert body['status'] == DocumentStatus.COMPLETED.value
        # The register's number, not the draft's identifier: confirmation
        # happened in the same transaction as the posting.
        assert not body['number'].startswith('DRAFT-')

        db_session.expire_all()
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('95')

    def test_creating_and_posting_from_scratch_is_one_call(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        posted = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json=_dispatch_payload(
                partner_id=doc_partner,
                source_location_id=doc_source_location,
                item=doc_stock_item,
                quantity=3,
            ),
        )
        assert posted.status_code == status.HTTP_201_CREATED, posted.text
        body = posted.json()
        assert body['status'] == DocumentStatus.COMPLETED.value
        assert not body['number'].startswith('DRAFT-')

        db_session.expire_all()
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('97')

    def test_a_completion_that_fails_leaves_the_draft_untouched(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json=_dispatch_payload(
                partner_id=doc_partner,
                source_location_id=doc_source_location,
                item=doc_stock_item,
                quantity=5,
            ),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])
        draft_number = created.json()['number']

        from app.modules.warehouse import _document_workflow_transitions as t

        async def _boom(*_args: object, **_kwargs: object) -> None:
            raise ValueError('simulated stock posting failure')

        monkeypatch.setattr(t, 'execute_stock_operations', _boom)

        posted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )
        assert posted.status_code >= 400, posted.text

        db_session.expire_all()
        doc = db_session.get(Document, doc_id)
        assert doc is not None
        # Confirmation had already drawn a number and reserved the stock
        # before the posting failed; neither survives the rollback.
        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.number == draft_number
        reservations = db_session.scalar(
            select(func.count())
            .select_from(StockReservation)
            .where(StockReservation.document_id == doc.id)
        )
        assert reservations == 0
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('100')


@pytest.mark.integration
class TestApprovalFinishesTheOneStepPosting:
    def test_the_approval_posts_the_document_without_another_step(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        doc_approval_workflow: ApprovalWorkflow,
        approver_notices: list[str],
    ) -> None:
        _set_threshold(client, doc_auth_headers, '1.00')
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json=_dispatch_payload(
                partner_id=doc_partner,
                source_location_id=doc_source_location,
                item=doc_stock_item,
                quantity=5,
            ),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])

        posted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )
        assert posted.status_code == status.HTTP_200_OK, posted.text
        assert posted.json()['status'] == DocumentStatus.PENDING_APPROVAL.value
        # The approver hears of it once the request stands.
        assert any(notice.startswith('mail:') for notice in approver_notices)
        assert 'push' in approver_notices

        db_session.expire_all()
        waiting = db_session.get(Document, doc_id)
        assert waiting is not None
        assert waiting.complete_on_approval is True
        # Nothing moved while the approval stood in the way.
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('100')

        # The queue tells the approver what this decision will do: a document
        # submitted to be posted says so, instead of promising a later
        # execution step that this approval already performs.
        queue = client.get(
            '/api/v1/approvals/requests',
            headers=doc_auth_headers,
            params={'target_type': 'document'},
        )
        assert queue.status_code == status.HTTP_200_OK, queue.text
        request_row = next(
            row for row in queue.json()['items'] if row['target_id'] == doc_id
        )
        assert request_row['target_summary']['posts_on_approval'] is True

        approved = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text

        db_session.expire_all()
        finished = db_session.get(Document, doc_id)
        assert finished is not None
        assert finished.status == DocumentStatus.COMPLETED.value
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('95')

    def test_a_refused_post_into_an_approval_leaves_no_request_behind(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        doc_approval_workflow: ApprovalWorkflow,
        approver_notices: list[str],
    ) -> None:
        _set_threshold(client, doc_auth_headers, '1.00')
        # More than the shelf holds: the reservation is refused after the
        # approval request has been raised, so the request must go with it.
        payload = _dispatch_payload(
            partner_id=doc_partner,
            source_location_id=doc_source_location,
            item=doc_stock_item,
            quantity=99999,
        )
        created = client.post(
            '/api/v1/warehouse/documents', headers=doc_auth_headers, json=payload
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])
        draft_number = created.json()['number']
        documents_before = db_session.scalar(select(func.count()).select_from(Document))

        for refused in (
            client.post(
                f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
            ),
            client.post(
                '/api/v1/warehouse/documents/post',
                headers=doc_auth_headers,
                json=payload,
            ),
        ):
            assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text

        db_session.expire_all()
        doc = db_session.get(Document, doc_id)
        assert doc is not None
        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.number == draft_number
        assert (
            db_session.scalar(select(func.count()).select_from(Document))
            == documents_before
        )
        assert db_session.scalar(select(func.count()).select_from(ApprovalRequest)) == 0
        # Nor was anybody told to decide a request that never stood: the mail
        # and the push leave the transaction, so they wait for its commit.
        assert approver_notices == []

    @pytest.mark.parametrize('door', ['document', 'queue'])
    def test_an_approval_whose_posting_is_refused_is_refused_too(
        self,
        door: str,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        _set_threshold(client, doc_auth_headers, '1.00')
        posted = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json=_dispatch_payload(
                partner_id=doc_partner,
                source_location_id=doc_source_location,
                item=doc_stock_item,
                quantity=5,
            ),
        )
        assert posted.status_code == status.HTTP_201_CREATED, posted.text
        assert posted.json()['status'] == DocumentStatus.PENDING_APPROVAL.value
        doc_id = cast(str, posted.json()['id'])

        # The month closes while the document waits: the posting the approval
        # promised can no longer happen.
        today = datetime.now(UTC)
        closed = client.post(
            f'/api/v1/warehouse/periods/{today.year}/{today.month}/close',
            headers=doc_auth_headers,
        )
        assert closed.status_code == status.HTTP_200_OK, closed.text

        if door == 'document':
            approved = client.post(
                f'/api/v1/approvals/documents/{doc_id}/approve',
                headers=doc_auth_headers,
            )
        else:
            request_id = db_session.scalar(
                select(ApprovalRequest.id).where(ApprovalRequest.target_id == doc_id)
            )
            approved = client.post(
                f'/api/v1/approvals/requests/{request_id}/approve',
                headers=doc_auth_headers,
            )
        # The approver hears why, and nothing of the decision stands: an
        # approval that leaves the document confirmed but unposted would
        # break the promise the dialog made.
        assert approved.status_code >= 400, approved.text

        db_session.expire_all()
        doc = db_session.get(Document, doc_id)
        assert doc is not None
        assert doc.status == DocumentStatus.PENDING_APPROVAL.value
        request_status = db_session.scalar(
            select(ApprovalRequest.status).where(ApprovalRequest.target_id == doc_id)
        )
        assert request_status != 'APPROVED'
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('100')
