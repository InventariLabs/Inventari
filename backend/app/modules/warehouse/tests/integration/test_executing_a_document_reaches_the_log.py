"""Executing a document is the step the stock turns on, so it earns an entry.

Creating and confirming were logged; executing was not. The organization log
therefore held documents that were made and changed and never appeared to
have moved anything, while the goods had already left the shelf — and the
module's own purpose card promises that "months later somebody can be shown
why the numbers are what they are".

The quantity rows the execution writes had the same gap from the other side.
They carried the document's type and number but no reason, so a receipt
moving a hundred units was indistinguishable from a manual edit, and no
identifier tied the row back to the document that caused it.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _entries(db_session: Session, org_id: UUID, target_type: str) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == target_type,
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


@pytest.mark.integration
class TestExecutingADocumentReachesTheLog:
    def _receive(
        self,
        client: TestClient,
        headers: dict[str, str],
        *,
        partner_id: UUID,
        target_location_id: UUID,
        template_id: UUID,
    ) -> str:
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'IN',
                'partner_id': str(partner_id),
                'target_location_id': str(target_location_id),
                'lines': [
                    {'product_template_id': str(template_id), 'expected_quantity': 100}
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        return doc_id

    def test_completion_leaves_its_own_entry(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        template = ModuleTestHelper(db_session).create_template(
            doc_org, name=f'Logged IN {uuid4().hex[:6]}'
        )

        doc_id = self._receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
        )

        db_session.expire_all()
        completed = [
            entry
            for entry in _entries(db_session, doc_org.id, 'document')
            if entry.reason == 'document_completed'
        ]
        assert len(completed) == 1, 'executing the document left no entry'

        snapshot = completed[0].snapshot
        assert snapshot is not None
        assert str(completed[0].target_id) == doc_id
        # The number, not the id: the log is read by a person, and a
        # document is known by what is printed on it.
        assert snapshot['number']
        assert snapshot['new_status'] == 'COMPLETED'
        assert snapshot['lines'] == 1

    def test_the_quantity_row_says_which_document_moved_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_stock_item: Item,
        doc_template: ProductTemplate,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        # Received onto the shelf the product already stands on, so the
        # execution raises a quantity rather than creating a record — a
        # receipt of an unknown product takes the create path and never
        # reaches the row this test is about.
        assert doc_stock_item.storage_location_id == doc_source_location.id

        doc_id = self._receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=doc_template.id,
        )

        db_session.expire_all()
        from_document = [
            entry
            for entry in _entries(db_session, doc_org.id, 'item')
            if entry.reason == 'document_execution'
        ]
        assert from_document, 'the quantity change did not say why it happened'

        meta = from_document[0].meta_data
        assert meta is not None
        assert meta['source_document_id'] == doc_id
        assert meta['document_number']

    def test_a_corrections_quantity_row_says_why_and_what_it_corrects(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_stock_item: Item,
        doc_template: ProductTemplate,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """A quantity row a correction wrote named the two documents but not
        the reason: it read as a manual edit beside the receipt rows that
        carry one, and the correction's number was the only half on the row.
        """
        assert doc_stock_item.storage_location_id == doc_source_location.id

        doc_id = self._receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=doc_template.id,
        )
        original = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert original.status_code == status.HTTP_200_OK, original.text
        line_number = original.json()['lines'][0]['line_number']

        created = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': line_number, 'quantity_delta': -10}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        correction = created.json()
        corr_id = correction['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        # The number the register knows is the one given out at
        # confirmation, and the one the execution writes on its row.
        issued_number = confirm.json()['number']
        complete = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        db_session.expire_all()
        corrected = [
            entry
            for entry in _entries(db_session, doc_org.id, 'item')
            if entry.action == 'QUANTITY_CHANGE'
            and (entry.meta_data or {}).get('corrects_document_number')
        ]
        assert corrected, 'the correction wrote no row naming what it corrects'

        entry = corrected[0]
        assert entry.reason == 'document_execution', (
            'the correction reads as a manual edit — it carries no reason'
        )
        meta = entry.meta_data
        assert meta is not None
        assert meta['document_number'] == issued_number
        assert meta['corrects_document_number'] == original.json()['number']

    def test_a_transfers_move_row_names_the_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_stock_item: Item,
        doc_template: ProductTemplate,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """A move a document executed carried no reference to it, so the row
        could not be told from a hand move and answered nothing about which
        document the goods followed.
        """
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        document = created.json()
        doc_id = document['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        issued_number = confirm.json()['number']
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        db_session.expire_all()
        moves = [
            entry
            for entry in _entries(db_session, doc_org.id, 'item')
            if entry.action == 'MOVE'
        ]
        assert len(moves) == 1, 'executing the transfer left no move entry'

        entry = moves[0]
        meta = entry.meta_data
        assert meta is not None, 'the move row says nothing about its document'
        assert meta['document_number'] == issued_number
        assert meta['source_document_id'] == doc_id
        assert entry.reason == 'document_execution'

    def test_creating_one_names_the_partner_it_points_at(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """`Partner: 7c65b0dd` is not an answer to who the goods came from.

        The create entry carried the id alone while the validation a line
        above had already read the row it names.
        """
        template = ModuleTestHelper(db_session).create_template(
            doc_org, name=f'Logged partner {uuid4().hex[:6]}'
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'product_template_id': str(template.id), 'expected_quantity': 5}
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        db_session.expire_all()
        entry = next(
            e
            for e in _entries(db_session, doc_org.id, 'document')
            if e.action == 'CREATE' and str(e.target_id) == created.json()['id']
        )
        assert entry.snapshot is not None
        assert entry.snapshot['partner_id'] == str(doc_partner.id)
        assert entry.snapshot['partner_name'] == 'Acme Supplies'
