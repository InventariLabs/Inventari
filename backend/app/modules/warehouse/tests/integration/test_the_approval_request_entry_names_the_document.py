"""The approval entry in the organization log names the document it guards.

An entry about an approval request showed the request's uuid and its type
-- "8d6f4bf7 Wniosek o akceptację" -- so an auditor filtering the log for a
document number found the question the log recorded and no answer to which
document it belonged to. The entry now carries the target's own number,
taken from the provider whoever owns the target type registered.
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
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalWorkflow


def _confirmed_document(
    client: TestClient,
    headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_item: Item,
) -> dict[str, str]:
    """A receipt over the threshold, confirmed into the approval queue."""
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
            'approval_threshold': '100.00',
            'approval_required_for_types': [],
            'value_tracking_enabled': True,
        },
    )
    assert put.status_code == status.HTTP_200_OK, put.text

    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'item_id': str(doc_item.id),
                    'expected_quantity': 5,
                    'unit_price': '50.00',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    document: dict[str, Any] = created.json()

    confirm = client.patch(
        f'/api/v1/warehouse/documents/{document["id"]}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    assert confirm.json()['status'] == 'PENDING_APPROVAL'
    # The number is given out at confirmation, before the request is
    # raised on top of it — which is the number the request's entry
    # carries.
    return {'id': str(document['id']), 'number': str(confirm.json()['number'])}


@pytest.mark.integration
class TestTheApprovalRequestEntryNamesTheDocument:
    def test_the_entry_carries_the_document_number(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_org: Organization,
    ) -> None:
        document = _confirmed_document(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )

        entries = list(
            db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == doc_org.id,
                    AuditLog.target_type == 'approval_request',
                )
            ).all()
        )
        assert entries, 'raising the request left no entry in the log'
        entry = entries[0]
        assert entry.snapshot is not None
        approves = entry.snapshot['approves']
        assert approves['type'] == 'document'
        assert approves['id'] == document['id']
        # The number is what the auditor came to read: the request's own
        # uuid names nothing they can find.
        assert approves['number'] == document['number']
