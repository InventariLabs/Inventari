"""Editing, deleting, correcting and costing a document reach the log.

Confirming, executing and cancelling were journaled — the rest of the
lifecycle was not: a manager who edited a draft, deleted one, named a
receipt line's shelf, corrected a completed delivery or dropped a freight
cost left the organization log silent, and "who removed this" had no
answer three months later.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document, DocumentLine


def _entries(db_session: Session, org_id: UUID, doc_id: str) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'document',
                AuditLog.target_id == doc_id,
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


def _completed_delivery(
    db_session: Session,
    org_id: UUID,
    user_id: Any,
    partner_id: UUID,
    location_id: UUID,
    template_id: UUID,
    item_id: UUID,
    *,
    number: str,
) -> Document:
    """A delivered receipt, seeded the way the receipt door leaves it."""
    doc = Document(
        organization_id=org_id,
        type='IN',
        number=number,
        status='COMPLETED',
        partner_id=partner_id,
        target_location_id=location_id,
        created_by=user_id,
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        DocumentLine(
            document_id=doc.id,
            item_id=item_id,
            product_template_id=template_id,
            quantity=Decimal('5'),
            expected_quantity=Decimal('5'),
            done_quantity=Decimal('5'),
            line_number=1,
            executed_location_id=location_id,
        )
    )
    db_session.commit()
    db_session.refresh(doc)
    return doc


@pytest.mark.integration
class TestDocumentLifecycleReachesTheLog:
    def test_editing_a_draft_reaches_the_log(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_draft_pz: Document,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        edited = client.put(
            f'/api/v1/warehouse/documents/{doc_draft_pz.id}',
            headers=doc_auth_headers,
            json={'notes': 'edited by the test'},
        )
        assert edited.status_code == status.HTTP_200_OK, edited.text

        db_session.expire_all()
        entries = _entries(db_session, doc_org.id, str(doc_draft_pz.id))
        updates = [entry for entry in entries if entry.action == 'UPDATE']
        assert updates, 'editing the draft left no entry in the log'
        snapshot = updates[0].snapshot or {}
        assert snapshot['number'] == doc_draft_pz.number
        assert 'notes' in snapshot['fields']
        assert updates[0].user_id is not None

    def test_deleting_a_draft_reaches_the_log(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_draft_pz: Document,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        doc_id = str(doc_draft_pz.id)
        number = doc_draft_pz.number
        deleted = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert deleted.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        ), deleted.text

        db_session.expire_all()
        entries = _entries(db_session, doc_org.id, doc_id)
        deletes = [entry for entry in entries if entry.action == 'HARD_DELETE']
        assert deletes, 'deleting the draft left no entry in the log'
        # The record is gone — the number travels in the snapshot, or the
        # entry answers an id nobody can look up.
        assert (deletes[0].snapshot or {}).get('number') == number
        assert deletes[0].user_id is not None

    def test_naming_a_line_shelf_reaches_the_log(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_draft_pz: Document,
        doc_source_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        line_id = str(doc_draft_pz.lines[0].id)
        named = client.patch(
            f'/api/v1/warehouse/documents/{doc_draft_pz.id}/lines/{line_id}',
            headers=doc_auth_headers,
            json={'target_location_id': str(doc_source_location.id)},
        )
        assert named.status_code == status.HTTP_200_OK, named.text

        db_session.expire_all()
        entries = _entries(db_session, doc_org.id, str(doc_draft_pz.id))
        updates = [entry for entry in entries if entry.action == 'UPDATE']
        assert updates, 'naming the line shelf left no entry in the log'
        snapshot = updates[0].snapshot or {}
        assert snapshot['fields'] == ['target_location_id']
        assert snapshot['line_id'] == line_id
        assert snapshot['new_target_location_id'] == str(doc_source_location.id)

    def test_a_correction_reaches_the_log(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: Any,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: Any,
        doc_item: Any,
        db_session: Session,
    ) -> None:
        original = _completed_delivery(
            db_session,
            doc_org.id,
            doc_user.id,
            doc_partner.id,
            doc_target_location.id,
            doc_template.id,
            doc_item.id,
            number=f'IN/JRNL/{uuid4().hex[:8]}',
        )
        created = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': str(original.id),
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {'original_line_number': 1, 'quantity_delta': -1},
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        correction_id = cast(str, created.json()['id'])

        db_session.expire_all()
        entries = _entries(db_session, doc_org.id, correction_id)
        creates = [entry for entry in entries if entry.action == 'CREATE']
        assert creates, 'creating the correction left no entry in the log'
        snapshot = creates[0].snapshot or {}
        assert snapshot['corrects_number'] == original.number
        assert snapshot['reason_code'] == 'DATA_ENTRY_ERROR'

    def test_a_return_reaches_the_log(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: Any,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: Any,
        doc_item: Any,
        db_session: Session,
    ) -> None:
        original = _completed_delivery(
            db_session,
            doc_org.id,
            doc_user.id,
            doc_partner.id,
            doc_target_location.id,
            doc_template.id,
            doc_item.id,
            number=f'IN/JRNL/{uuid4().hex[:8]}',
        )
        created = client.post(
            f'/api/v1/warehouse/documents/{original.id}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        return_id = cast(str, created.json()['id'])

        db_session.expire_all()
        entries = _entries(db_session, doc_org.id, return_id)
        creates = [entry for entry in entries if entry.action == 'CREATE']
        assert creates, 'creating the return left no entry in the log'
        snapshot = creates[0].snapshot or {}
        assert snapshot['number']
        assert snapshot['original_number'] == original.number
        assert snapshot['reason_code'] == 'DAMAGED'

    def test_extra_costs_reach_the_log(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_draft_pz: Document,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        doc_id = str(doc_draft_pz.id)
        added = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={
                'kind': 'freight',
                'amount': '10.50',
                'allocation_method': 'value',
            },
        )
        assert added.status_code == status.HTTP_201_CREATED, added.text
        cost_id = cast(str, added.json()['costs'][0]['id'])

        db_session.expire_all()
        entries = _entries(db_session, doc_org.id, doc_id)
        creates = [entry for entry in entries if entry.action == 'CREATE']
        assert creates, 'adding the extra cost left no entry in the log'
        snapshot = creates[0].snapshot or {}
        assert snapshot['cost_kind'] == 'freight'
        assert snapshot['amount'] == '10.50'

        removed = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs/{cost_id}',
            headers=doc_auth_headers,
        )
        assert removed.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        ), removed.text

        db_session.expire_all()
        entries = _entries(db_session, doc_org.id, doc_id)
        assert doc_draft_pz.id is not None
        deletes = [
            entry
            for entry in entries
            if entry.action in ('HARD_DELETE', 'SOFT_DELETE', 'DELETE')
        ]
        assert deletes, 'removing the extra cost left no entry in the log'
        assert (deletes[0].snapshot or {}).get('cost_kind') == 'freight'
