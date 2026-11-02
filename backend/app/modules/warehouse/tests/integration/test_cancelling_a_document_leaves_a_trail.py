"""Cancelling a document leaves a trail, like every other transition.

Confirming was logged, executing was logged — cancelling was
not, and the row carried no canceller either. So a manager who took a
confirmed receipt out of the books left the organization log silent and
the card unable to say who withdrew the document and when: three months
later the cancellation had no author, no time, and no entry.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document, DocumentStatus


def _document(db_session: Session, doc_id: UUID) -> Document | None:
    return db_session.scalar(select(Document).where(Document.id == doc_id))


def _entries(db_session: Session, org_id: UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'document',
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    target_location_id: UUID,
    item_payload: dict[str, Any],
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [item_payload],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id


@pytest.mark.integration
class TestCancellingADocumentLeavesATrail:
    def test_cancellation_reaches_the_log_with_its_author_and_time(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Any,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        doc_id = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            item_payload={'item_id': str(doc_item.id), 'expected_quantity': 5},
        )

        cancelled = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert cancelled.status_code == status.HTTP_200_OK, cancelled.text

        db_session.expire_all()
        entries = [
            entry
            for entry in _entries(db_session, doc_org.id)
            if entry.reason == 'document_cancelled'
        ]
        assert entries, 'cancelling the document left no entry in the log'

        entry = entries[0]
        assert str(entry.target_id) == doc_id
        # The canceller and the time are the two things the log exists for:
        # without them the entry says "somebody, at some point".
        assert entry.user_id is not None
        assert entry.created_at is not None
        snapshot = entry.snapshot
        assert snapshot is not None
        assert snapshot['new_status'] == DocumentStatus.CANCELLED.value
        assert snapshot['old_status'] == DocumentStatus.CONFIRMED.value
        # The number, not the id — the log is read by a person.
        assert snapshot['number']

    def test_the_row_names_the_canceller(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Any,
        db_session: Session,
    ) -> None:
        doc_id = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            item_payload={'item_id': str(doc_item.id), 'expected_quantity': 5},
        )

        cancelled = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert cancelled.status_code == status.HTTP_200_OK, cancelled.text

        body = cancelled.json()
        assert body['status'] == DocumentStatus.CANCELLED.value
        # The card's "who and when" comes from the response itself.
        assert body['cancelled_by_name']
        assert body['cancelled_at'] is not None

        db_session.expire_all()
        doc = _document(db_session, UUID(doc_id))
        assert doc is not None
        assert doc.cancelled_by is not None
        assert doc.cancelled_at is not None
